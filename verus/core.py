# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_core.ipynb.

# %% auto 0
__all__ = ['SOURCE_ROOT', 'Task', 'activate']

# %% ../nbs/00_core.ipynb 3
import textwrap
import json
import requests
import os
import docker
import typing
import tarfile
import jupytext
import sched
import time
import importlib.util
import inspect

# %% ../nbs/00_core.ipynb 5
# TODO: The func list arg generation from input
# is going to have to be more robust


def _input_value_to_arg_value(value):
    return f"'value'" if isinstance(value, str) else value


def _task_to_script(wf_name, task_name, task_source, automations, input):
    return f"""\
# %%
import {wf_name}

{wf_name}.{task_name}({", ".join([f"{key}={_input_value_to_arg_value(value)}" for key, value in input.items()])})

# %%
from data_chimp_executor import execute as dchimp
dchimp.on_cell_execute('''{task_source}''', '{json.dumps(automations)}', globals() | json.loads('{json.dumps(input)}'))
  """

# %% ../nbs/00_core.ipynb 7
def _update_task_status(host, task, status):
    requests.post(
        f"{host}/updateTask/{task['job_run_id']}",
        data={
            'task_name': task['name'],
            'status': status
        },
        headers={'x-token': os.environ.get('CHIMP_TOKEN')}
    )


class Task(typing.TypedDict):
    job_run_id: int
    name: str
    image: str | None
    code_nb_path: str
    applets_nb_path: str
    input: dict


SOURCE_ROOT = '/data_chimp/source'


def _get_source(task: Task, root=SOURCE_ROOT):
    spec = importlib.util.spec_from_file_location(
        "workflow", f"{root}/{task['code_nb_path']}")
    workflow_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workflow_module)
    return inspect.getsource(getattr(workflow_module, task['name']))

# %% ../nbs/00_core.ipynb 9
def _get_automations(path: str, root=SOURCE_ROOT) -> list:
    node = jupytext.read(f"{root}/{path}")
    return [
        {"id": "", "code": cell['source']}
        for cell in node.cells
        if cell['cell_type'] == "code" and "dchimp.ignore" not in cell['metadata'].get('tags', [])
    ]

# %% ../nbs/00_core.ipynb 11
def _execute():
    host = os.environ.get("ORCHESTRATION_SERVER", "https://the.datachimp.app")
    r = requests.get(f"{host}/getTasks",
                     headers={'x-token': os.environ.get('CHIMP_TOKEN')})
    r.raise_for_status()
    tasks: typing.List[Task] = r.json()
    if len(tasks['data']) == 0:
        return
    task, *_ = tasks['data']
    _update_task_status(host, task, 'started')
    client = docker.from_env()
    print("initiated docker client")
    image = task.get('image', 'jupyter/tensorflow-notebook')
    print("pulling image")
    client.images.pull(image)
    print("image pulled")
    # Transform code at code_nb_path into a notebook
    script = _task_to_script(task["wf_name"],
                             task["name"],
                             _get_source(task, os.environ.get('SOURCE_ROOT')),
                             # TODO: Make it possible to run multiple applets that are selected by the user
                             # just like you can toggle applets within VSCode
                             _get_automations(
                                 task['applets_nb_path'], os.environ.get('SOURCE_ROOT')),
                             task["input"]
                             )
    jupytext.write(jupytext.reads(script, fmt="py:percent"),
                   "data_chimp_notebook.ipynb")
    print("notebook created")
    container = client.containers.run(
        image,
        tty=True,
        command="/bin/bash",
        detach=True
    )
    print("container run")
    # TODO: We'll need to copy more than just the module that has the workflow
    # because the workflow could reference functions defined in other files.
    # We'll probably have to pass the whole codebase. Would be nice if this was
    # just a python package...maybe it could be if we assume usage of nbdev
    with (
        tarfile.open('code.tar', mode='w') as tar_f,
    ):
        tar_f.add(
            f"{os.environ.get('SOURCE_ROOT', SOURCE_ROOT)}/{task['code_nb_path']}",
            f"{task['wf_name']}.py"
        )
        tar_f.add("data_chimp_notebook.ipynb")
    container.exec_run("mkdir -p data_chimp/source")
    with open('code.tar') as tar_f:
        container.put_archive('/home/jovyan/data_chimp/source', tar_f)
    _update_task_status(host, task, 'env_ready')
    container.exec_run(
        "cp data_chimp/source/data_chimp_notebook.ipynb data_chimp/source/data_chimp_notebook_writable.ipynb"
    )

    # TODO: Run this function as a subprocess every few seconds so the orchestrator knows the build is still
    # progressing
    _update_task_status(host, task, 'executing')
    container.exec_run(
        'jupyter nbconvert --inplace --allow-errors --execute data_chimp/source/data_chimp_notebook_writable.ipynb'
    )

    # Collect notebook results and post to orchestration server
    _bytes, _ = container.get_archive(
        '/home/jovyan/data_chimp/source/data_chimp_notebook_writable.ipynb'
    )
    with open('./sh_bin.tar', 'wb') as f:
        for chunk in _bytes:
            f.write(chunk)
    with tarfile.open('./sh_bin.tar', mode='r') as f:
        f.extractall(path="output")
    with open('output/data_chimp_notebook_writable.ipynb') as f:
        nb = json.load(f)
        requests.post(
            f"{host}/updateTask/{task['job_run_id']}",
            data={
                'task_name': task['name'],
                'status': 'done',
                'nb': nb
            }
        )
    container.stop()
    container.remove()


def _run_every(func, sec=5):
    s = sched.scheduler(time.time, time.sleep)

    def do_something(sc):
        print("Doing stuff...")
        func()
        sc.enter(sec, 1, do_something, (sc,))

    s.enter(sec, 1, do_something, (s,))
    s.run()

# %% ../nbs/00_core.ipynb 12
def activate():
    _run_every(_execute, 5)


# %% ../nbs/00_core.ipynb 13
if __name__ == "__main__":
    activate()