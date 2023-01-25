# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_core.ipynb.

# %% auto 0
__all__ = ['Task', 'get_imports_source', 'activate']

# %% ../nbs/00_core.ipynb 3
import argparse
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
import ast
import subprocess
import time

# %% ../nbs/00_core.ipynb 5
class Task(typing.TypedDict):
    job_run_id: int
    name: str
    image: str | None
    code_nb_path: str
    applets_nb_path: str
    input: dict

def _get_source(task: Task, root: str):
    spec = importlib.util.spec_from_file_location(
        "workflow", f"{root}/{task['code_nb_path']}")
    workflow_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workflow_module)
    # getattr returns a DunderFunc
    func_source = inspect.getsource(getattr(workflow_module, task['name']).func)
    func_body = ast.parse(func_source).body[0].body
    if not isinstance(func_body, list):
        return ast.unparse(func_body)
    func_body_drop_return = [el.value if isinstance(el, ast.Return) else el for el in func_body]
    unparsed = map(ast.unparse, func_body_drop_return)
    return "\n".join(unparsed)

# %% ../nbs/00_core.ipynb 7
def get_imports_source(path):
    with open(path) as f:
      source = f.read()
      parsed_source = ast.parse(source)
      return ast.unparse([n for n in ast.walk(parsed_source) if isinstance(n, (ast.Import, ast.ImportFrom))])

# %% ../nbs/00_core.ipynb 9
# TODO: The func list arg generation from input
# is going to have to be more robust
def _input_value_to_arg_value(value):
    return f"'value'" if isinstance(value, str) else value

def _task_to_script(task, automations, root):
    task_source = _get_source(task, root)
    imports_source = get_imports_source(f"{root}/{task['code_nb_path']}")
    return f"""\
# %%
{imports_source}
import {task['wf_name']}

{task['wf_name']}.{task['name']}({", ".join([f"{key}={_input_value_to_arg_value(value)}" for key, value in task['input'].items()])})

# %%
import json
dchimp.on_execute_cell('''{json.dumps({"code": task_source})}''', '{json.dumps(automations)}', globals() | json.loads('{json.dumps(task['input'])}'))
"""

# %% ../nbs/00_core.ipynb 11
def _update_task_status(host, task, status):
    requests.post(
        f"{host}/updateTask/{task['job_run_id']}",
        json={
            'task_name': task['name'],
            'status': status
        },
        headers={'x-token': os.environ.get('CHIMP_TOKEN')}
    ).raise_for_status()

# %% ../nbs/00_core.ipynb 12
def _get_automations(path: str, root: str) -> list:
    node = jupytext.read(f"{root}/{path}")
    return [
        {"id": "", "code": cell['source']}
        for cell in node.cells
        if cell['cell_type'] == "code" and "dchimp.ignore" not in cell['metadata'].get('tags', [])
    ]

# %% ../nbs/00_core.ipynb 14
def _execute():
    if os.environ.get('CHIMP_TOKEN') is None:
        print("CHIMP_TOKEN env variable missing")
        exit(1)
    if os.environ.get('WORKFLOW_REPO') is None and os.environ.get('SOURCE_ROOT') is None:
        print("WORKFLOW_REPO env variable missing")
        exit(1)
    print("Polling for available jobs")
    host = os.environ.get("ORCHESTRATION_SERVER", "https://the.datachimp.app")
    
    r = requests.get(f"{host}/getTasks",
                     headers={'x-token': os.environ.get('CHIMP_TOKEN')})
    r.raise_for_status()
    tasks: typing.List[Task] = r.json()
    if len(tasks['data']) == 0:
        print("no tasks. Trying again later...")
        return
    root = f'workflow_repo_{int(time.time())}'
    if os.environ.get('SOURCE_ROOT') is None:       
        print("cloning repo")
        subprocess.run(['git', 'clone', os.environ.get("WORKFLOW_REPO"), root])
    task, *_ = tasks['data']
    print(f"received task: {task}")
    _update_task_status(host, task, 'started')
    client = docker.from_env()
    print("initiated docker client")
    image = task.get('image', 'jupyter/tensorflow-notebook')
    print("pulling image")
    client.images.pull(image)
    print("image pulled")
    # Transform code at code_nb_path into a notebook
    script = _task_to_script(task,
                             # TODO: Make it possible to run multiple applets that are selected by the user
                             # just like you can toggle applets within VSCode
                             _get_automations(
                                 task['applets_nb_path'], os.environ.get('SOURCE_ROOT', root)
                             ),
                             os.environ.get('SOURCE_ROOT', root)
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
    print("container started")
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
    container.exec_run(
        "cp data_chimp/source/data_chimp_notebook.ipynb data_chimp/source/data_chimp_notebook_writable.ipynb"
    )
    container.exec_run(
        "wget https://github.com/getdatachimp/verus/raw/main/data_chimp_executor-0.1.0-py2.py3-none-any.whl",
        stream=True
    )
    container.exec_run('pip install data_chimp_executor-0.1.0-py2.py3-none-any.whl')
    _update_task_status(host, task, 'env_ready')
    print("source copied to container")
    # TODO: Run this function as a subprocess every few seconds so the orchestrator knows the build is still
    # progressing
    _update_task_status(host, task, 'executing')
    container.exec_run(
        'jupyter nbconvert --inplace --allow-errors --execute data_chimp/source/data_chimp_notebook_writable.ipynb'
    )
    print("finished task, sending results to data chimp")
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
        r = requests.post(
            f"{host}/updateTask/{task['job_run_id']}",
            json={
                'task_name': task['name'],
                'status': 'done',
                'nb': nb
            },
            headers={
                'x-token': os.environ.get('CHIMP_TOKEN')
            }
        )
        try: 
            r.raise_for_status()
        except Exception as e:
            print("failed to update task status because of error:")
            print(e)
        finally:
            container.stop()
            if not os.environ.get('DC_DEBUG'):
                container.remove()
            print("task container stopped and removed")


def _run_every(func, sec=5):
    s = sched.scheduler(time.time, time.sleep)

    def do_something(sc):
        func()
        sc.enter(sec, 1, do_something, (sc,))

    s.enter(sec, 1, do_something, (s,))
    s.run()

# %% ../nbs/00_core.ipynb 15
def activate():
    _run_every(_execute, 5)
