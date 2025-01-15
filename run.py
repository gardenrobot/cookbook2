import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from threading import Lock
from jinja2 import Environment, FileSystemLoader
import os
from cooklang import Recipe
import shutil


lock = Lock()

BASE_DIR = os.path.dirname(__file__)
HTML_PATH = os.getenv("HTML_DIR", os.path.join(BASE_DIR, "html"))
RECIPE_DIR = os.getenv("RECIPE_DIR", os.path.join(BASE_DIR, "recipes"))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


def main():
    # TODO support pics

    # move static files into html dir
    html_static_path = HTML_PATH + "/static"
    shutil.rmtree(html_static_path, ignore_errors=True)
    shutil.copytree("static/", html_static_path)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    event_handler = CookbookEventHandler()
    observer = Observer()
    observer.schedule(event_handler, RECIPE_DIR, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


class CookbookEventHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        if event.is_directory:
            lock.acquire()
            render_dir(event.src_path)
            lock.release()
        return super().on_any_event(event)


def render_dir(path):
    assert path.startswith(RECIPE_DIR)
    rel_path = path[len(RECIPE_DIR) + 1 :]
    parent_folders = split_path(rel_path)
    _, sub_folders, files = next(os.walk(path))
    recipes = sorted([f[:-5] for f in files if f.endswith(".cook")])
    rendered = jinja_env.get_template("folder.html").render(
        parent_folders=parent_folders,
        sub_folders=sub_folders,
        recipes=recipes,
    )
    html_dir = os.path.join(HTML_PATH, rel_path)
    index_path = html_dir + "/index.html"
    try:
        os.makedirs(html_dir)
    except FileExistsError as e:
        pass
    with open(index_path, "w") as f:
        f.write(rendered)

    # recurse to subfolders
    for sub_folder in sub_folders:
        render_dir(os.path.join(path, sub_folder))
    # recurse to files
    for f in files:
        if f.endswith(".cook"):
            render_file(os.path.join(path, f))


def render_file(path):
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
        print(image_path)
        shutil.copy(image_path, html_dir + "/img")


def get_image_path(path):
    print(path)
    assert path.endswith(".cook")
    for ext in ["jpg", "png"]:
        fn = path[:-5] + "." + ext
        if os.path.exists(fn):
            return fn
    return None


def highlight_steps(ingredients, steps):
    # find indexes to insert highlighting
    indexes = []
    for ingr in ingredients:
        for step_index, step in enumerate(steps):
            if (start_index := step.find(ingr.name)) > -1:
                end_index = start_index + len(ingr.name)
                indexes.append((start_index, end_index, ingr, step_index))

    # sort the index high to low
    indexes.sort(key=lambda x: -x[0])

    # insert highlighting
    hl_steps = steps
    for start_index, end_index, ingr, step_index in indexes:
        step = hl_steps[step_index]

        hl = ""
        if ingr.quantity != None:
            hl += "<span class=ingr-name-inline>" + ingr.name + "</span>"
            hl += "<span class=ingr-quantity-inline>(" + str(ingr.quantity.amount)
            if ingr.quantity.unit:
                hl += " " + ingr.quantity.unit
            hl += ")</span>"

        step = step[:start_index] + hl + step[end_index:]
        hl_steps[step_index] = step

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
