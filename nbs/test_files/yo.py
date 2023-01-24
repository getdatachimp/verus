from data_chimp_executor import execute as dchimp


@dchimp.task
def task_one():
    return 1


@dchimp.task
def task_two():
    1


@dchimp.task
def task_three():
    x = 1
    return x


@dchimp.task
def task_four():
    x = 1
    y = 2
