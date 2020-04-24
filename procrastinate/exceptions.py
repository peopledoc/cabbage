import datetime


class ProcrastinateException(Exception):
    pass


class TaskNotFound(ProcrastinateException):
    pass


class JobError(ProcrastinateException):
    pass


class LoadFromPathError(ImportError, ProcrastinateException):
    pass


class JobRetry(ProcrastinateException):
    def __init__(self, scheduled_at: datetime.datetime):
        self.scheduled_at = scheduled_at


class PoolAlreadySet(ProcrastinateException):
    pass


class ConnectorException(ProcrastinateException):
    pass
