import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from threading import Lock
from jinja2 import Environment, FileSystemLoader
import os
from cooklang import Recipe
import shutil
import glob


lock = Lock()

BASE_DIR = os.path.dirname(__file__)
HTML_PATH = os.getenv("HTML_DIR", os.path.join(BASE_DIR, "html"))
RECIPE_DIR = os.getenv("RECIPE_DIR", os.path.join(BASE_DIR, "recipes"))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


def main():
    # TODO shut down more cleanly
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info("Starting up")

    logging.info("Copying static folder into html path")
    html_static_path = HTML_PATH + "/static"
    shutil.rmtree(html_static_path, ignore_errors=True)
    shutil.copytree("static/", html_static_path)

    logging.info("Setting up watch of recipe folder")
    event_handler = CookbookEventHandler()
    observer = Observer()
    observer.schedule(event_handler, RECIPE_DIR, recursive=True)
    observer.start()

    logging.info("Processing whole recipe folder")
    event = FileSystemEvent(RECIPE_DIR)
    event.is_directory = True
    event_handler.on_any_event(event)

    logging.info("Waiting...")
    try:
        while True:
            time.sleep(1)
    except Exception as e:
        logging.error("Exception while sleeping", exc_info=e)
        observer.stop()
    logging.info("Sleep over")
    observer.join()
    logging.info("Joined")


class CookbookEventHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        if event.is_directory:
            logging.info("Directory changed. Acquiring lock...")
            lock.acquire()
            logging.info("Lock acquired")
            try:
                render_dir(event.src_path)
            except Exception as e:
                logging.error(
                    "Error while processing directory %s", event.src_path, exc_info=e
                )
            finally:
                lock.release()
        return super().on_any_event(event)


def render_dir(path):
    logging.info("Processing folder %s", path)
    assert path.startswith(RECIPE_DIR)
    rel_path = path[len(RECIPE_DIR) + 1 :]
    html_dir = os.path.join(HTML_PATH, rel_path)

    logging.info("Deleting contents of old folder %s", html_dir)
    [
        shutil.rmtree(x, ignore_errors=True)
        for x in glob.glob(html_dir + "/*")
        if not x.endswith("/static")
    ]

    logging.info("Rendering html")
    parent_folders = split_path(rel_path)
    _, sub_folders, files = next(os.walk(path))
    sub_folders.sort()
    recipes = sorted([f[:-5] for f in files if f.endswith(".cook")])
    rendered = jinja_env.get_template("folder.html").render(
        parent_folders=parent_folders,
        sub_folders=sub_folders,
        recipes=recipes,
    )
    index_path = html_dir + "/index.html"
    try:
        os.makedirs(html_dir)
    except FileExistsError as e:
        pass
    with open(index_path, "w") as f:
        f.write(rendered)

    logging.info("Rendering done. Recursing...")
    # recurse to subfolders
    for sub_folder in sub_folders:
        render_dir(os.path.join(path, sub_folder))
    # recurse to files
    for f in files:
        if f.endswith(".cook"):
            render_file(os.path.join(path, f))


def render_file(path):
    logging.info("Processing file %s", path)
    assert path.startswith(RECIPE_DIR)
    rel_path = path[len(RECIPE_DIR) + 1 :]
    parent_folders = split_path(rel_path)
    # remove .cook ext from parent_folder's item
    parent_folders[-1] = parent_folders[-1][:-5]

    title = parent_folders[-1]
    with open(path) as f:
        txt = f.read()
        recipe = Recipe.parse(txt)
    highlighted_steps = highlight_steps(recipe.ingredients, recipe.steps)

    image_path = get_image_path(path)
    has_image = image_path != None

    # create a directory with the recipe path (minus the .cook extension)
    html_dir = os.path.join(HTML_PATH, rel_path)[:-5]
    try:
        os.makedirs(html_dir)
    except FileExistsError as e:
        pass

    # Save main file
    rendered_index = jinja_env.get_template("recipe.html").render(
        parent_folders=parent_folders,
        ingredients=recipe.ingredients,
        steps=highlighted_steps,
        metadata=recipe.metadata,
        title=title,
        has_image=has_image,
        is_printable=False,
        css="/static/styles.css",
    )
    with open(html_dir + "/index.html", "w") as f:
        f.write(rendered_index)

    # Save printable
    rendered_print = jinja_env.get_template("recipe.html").render(
        parent_folders=parent_folders,
        ingredients=recipe.ingredients,
        steps=highlighted_steps,
        metadata=recipe.metadata,
        title=title,
        has_image=has_image,
        is_printable=False,
        css="/static/printable.css",
    )
    with open(html_dir + "/print.html", "w") as f:
        f.write(rendered_print)

    # Copy .cook
    shutil.copy(path, html_dir)

    # Copy image
    if image_path:
        shutil.copy(image_path, html_dir + "/img")


def get_image_path(path):
    assert path.endswith(".cook")
    for ext in ["jpg", "png"]:
        fn = path[:-5] + "." + ext
        if os.path.exists(fn):
            return fn
    return None


def highlight_steps(ingredients, steps):
    """Takes ingredients and steps and returns modified steps that have html tags surrounding each ingredient"""
    pre_name = "<span class=ingr-name-inline>"
    post_name = "</span>"
    pre_quantity = "<span class=ingr-quantity-inline>("
    post_quantity = ")</span>"

    hl_steps = steps
    for ingr in reversed(sorted(ingredients, key=lambda x: x.location)):
        step_index = ingr.location[0]
        old_step = hl_steps[step_index]

        start_index = ingr.location[1]
        end_index = ingr.location[2]
        new_step = old_step[0:start_index] + "TODO" + old_step[end_index:]
        quantity_str = ""
        if ingr.quantity:
            quantity_str += f"{pre_quantity}{ingr.quantity.amount}"
            if ingr.quantity.unit:
                quantity_str += f" {ingr.quantity.unit}"
            quantity_str += post_quantity
        new_step = f"{old_step[0:start_index]}{pre_name}{ingr.name}{post_name}{quantity_str}{old_step[end_index:]}"

        hl_steps[step_index] = new_step
    return hl_steps


def split_path(path):
    """
    Takes a path under the RECIPE_DIR and returns the list of folders from the RECIPE_DIR to it.
    Ex: split_path("/tmp/recipe/bread/quickbreads/") -> ["bread", "quickbreads"]
    """
    parts = []
    headtail = (path, 0)
    while (headtail := os.path.split(headtail[0]))[0] not in ["", "/"]:
        parts.insert(0, headtail[1])
    parts.insert(0, headtail[1])
    if (head := headtail[0]) == "/":
        parts.insert(0, head)
    return parts


if __name__ == "__main__":
    main()
