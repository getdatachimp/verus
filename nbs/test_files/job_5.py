from data_chimp_executor import execute as dchimp


@dchimp.task
def task_one():
    pass


@dchimp.task
def task_two():
    pass


@dchimp.task
def task_three():
    pass


@dchimp.workflow
def a_wf():
    return task_one >> task_two >> task_three
