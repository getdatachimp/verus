from data_chimp_executor import execute as dchimp
import pandas as pd


@dchimp.task
def task_one():
    return pd.read_csv('https://raw.githubusercontent.com/getdatachimp/starter-repo-r/main/palmer_penguins.csv')


@dchimp.task
def task_two():
    pass


@dchimp.task
def task_three():
    pass


@dchimp.workflow
def a_wf():
    return task_one >> task_two >> task_three
