import logging
import time

from cabbage import exceptions, jobs, signals, store, tasks, types

logger = logging.getLogger(__name__)


SOCKET_TIMEOUT = 5  # seconds


class Worker:
    def __init__(self, task_manager: tasks.TaskManager, queue: str) -> None:
        self._task_manager = task_manager
        self._queue = queue
        self._stop_requested = False
        # Handling the info about the currently running task.
        self.log_context: types.JSONDict = {}

    @property
    def _job_store(self) -> store.JobStore:
        return self._task_manager.job_store

    def run(self, timeout: int = SOCKET_TIMEOUT) -> None:

        self._job_store.listen_for_jobs(queue=self._queue)

        with signals.on_stop(self.stop):
            while True:
                self.process_jobs()

                if self._stop_requested:
                    logger.debug(
                        "Finished running job at the end of the batch",
                        extra={"action": "stopped_end_batch"},
                    )
                    break

                logger.debug(
                    "Waiting for new jobs", extra={"action": "waiting_for_jobs"}
                )
                self._job_store.wait_for_jobs(timeout=timeout)

    def process_jobs(self) -> None:
        for job in self._job_store.get_jobs(self._queue):  # pragma: no branch
            assert isinstance(job.id, int)

            log_context = {"job": job._asdict(), "queue": self._queue}
            logger.debug(
                "Loaded job info, about to start job",
                extra={"action": "loaded_job_info", **log_context},
            )

            status = jobs.Status.ERROR
            try:
                self.run_job(job=job)
                status = jobs.Status.DONE
            except exceptions.JobError:
                pass
            finally:
                self._job_store.finish_job(job=job, status=status)
                logger.debug(
                    "Acknowledged job completion",
                    extra={"action": "finish_task", "status": status, **log_context},
                )

            if self._stop_requested:
                break

    def run_job(self, job: jobs.Job) -> None:
        task_name = job.task_name
        try:
            task = self._task_manager.tasks[task_name]
        except KeyError:
            raise exceptions.TaskNotFound(job)

        # We store the log context in self. This way, when requesting
        # a stop, we can get details on the currently running task
        # in the logs.
        start_time = time.time()
        log_context = self.log_context = {
            "queue": task.queue,
            "task_name": task.name,
            "id": job.id,
            "kwargs": job.kwargs,
            "start_timestamp": time.time(),
        }
        logger.info("Starting job", extra={"action": "start_job", "job": log_context})
        try:
            task(**job.kwargs)
        except Exception as e:
            end_time = log_context["end_timestamp"] = time.time()
            log_context["duration_seconds"] = end_time - start_time

            logger.exception(
                "Job error", extra={"action": "job_error", "job": log_context}
            )
            raise exceptions.JobError() from e
        else:
            end_time = log_context["end_timestamp"] = time.time()
            log_context["duration_seconds"] = end_time - start_time

            logger.info(
                "Job success", extra={"action": "job_success", "job": log_context}
            )

    def stop(self, signum: signals.Signals, frame: signals.FrameType) -> None:
        self._stop_requested = True
        log_context = self.log_context

        logger.info(
            "Stop requested, waiting for current job to finish",
            extra={"action": "stopping_worker", "job": log_context},
        )
