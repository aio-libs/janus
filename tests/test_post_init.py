import threading
import asyncio
import janus
import pytest

from concurrent.futures import ThreadPoolExecutor
from typing import Any


class TestOnlySync:
    tpe = ThreadPoolExecutor()

    def test_only_sync_init(self):
        queue: janus.Queue[int] = janus.Queue(init_async_part=False)
        assert not queue.already_initialized

    def test_only_sync_work(self):
        queue: janus.Queue[int] = janus.Queue(1, init_async_part=False)
        queue.sync_q.put(1)
        assert queue.sync_q.get() == 1
        queue.sync_q.task_done()

    def test_only_sync_get_two_threads_put(self):
        queue: janus.Queue[int] = janus.Queue(2, init_async_part=False)
        queue.sync_q.put(1)

        def put_some_n_times(n, sync_q: janus.SyncQueue):
            for i in range(n):
                sync_q.put(i)

        a_n = 5
        b_n = 7

        a_f = self.tpe.submit(put_some_n_times, a_n, queue.sync_q)
        b_f = self.tpe.submit(put_some_n_times, b_n, queue.sync_q)

        actual_n = 0
        while a_n + b_n > actual_n:
            queue.sync_q.get(timeout=3)
            queue.sync_q.task_done()
            actual_n += 1

        a_f.result()
        b_f.result()

        assert a_n + b_n == actual_n

    def test_sync_attempt_to_full_init(self):
        with pytest.raises(RuntimeError):
            janus.Queue(init_async_part=True)

    def test_sync_attempt_to_post_init_0(self):
        queue: janus.Queue[Any] = janus.Queue(init_async_part=False)
        with pytest.raises(RuntimeError):
            queue.trigger_async_initialization()

    def test_sync_attempt_to_post_init_1(self):
        queue: janus.Queue[Any] = janus.Queue(init_async_part=False)
        with pytest.raises(RuntimeError):
            queue.async_q.qsize()


class TestSyncThenPostInitAsync:
    tpe = ThreadPoolExecutor()

    def test_sync_then_async_0(self):
        queue: janus.Queue[Any] = janus.Queue(init_async_part=False)

        async def init_async(queue_: janus.Queue[Any]):
            queue_.trigger_async_initialization()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async(queue))

    def test_sync_then_async_1(self):
        queue: janus.Queue[Any] = janus.Queue(init_async_part=False)

        async def init_async(async_q: janus.AsyncQueue[Any]):
            async_q.qsize()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async(queue.async_q))

    def test_double_init(self):
        queue: janus.Queue[Any] = janus.Queue(init_async_part=False)

        async def init_async():
            queue.trigger_async_initialization()
            queue.trigger_async_initialization()
            queue.async_q.empty()
            assert isinstance(queue.async_q, janus._AsyncQueueProxy)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async())

    def test_full_init_with_wrong_coinitializers(self):
        class Queue(janus.Queue[Any]):
            @property
            def _also_initialize_when_triggered(self):
                return [None]

        queue: Queue = Queue(init_async_part=False)

        async def init_async():
            with pytest.raises(ValueError):
                queue.trigger_async_initialization()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async())

    def test_sync_put_then_async_get(self):
        _data = [i for i in range(10)]
        queue: janus.Queue[Any] = janus.Queue(maxsize=len(_data), init_async_part=False)

        for i in _data:
            queue.sync_q.put(i)
            assert queue.sync_q.qsize() == i + 1

        async def init_async(async_q: janus.AsyncQueue[Any]):
            it = iter(_data)

            while not async_q.empty():
                i = await async_q.get()
                async_q.task_done()
                assert i == next(it)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async(queue.async_q))
        queue.close()
        loop.run_until_complete(queue.wait_closed())

    def test_producer_threads_wait_until_init(self):
        num_of_threads = 3
        items = 6

        queue: janus.Queue[Any] = janus.Queue(maxsize=num_of_threads * items, init_async_part=False)
        barrier = threading.Barrier(num_of_threads + 1)

        def put_something_after_init(thr_num):
            queue.full_init.wait()

            for i in range(1, items + 1):
                queue.sync_q.put((thr_num, i * thr_num))

            barrier.wait()

        for thr_num in range(1, num_of_threads + 1):
            self.tpe.submit(put_something_after_init, thr_num)

        async def init_async(async_q: janus.AsyncQueue[Any]):
            while barrier.parties - 1 > barrier.n_waiting or not async_q.empty():
                thread_num, num = await async_q.get()
                async_q.task_done()
                assert num / (num / thread_num) == thread_num

            barrier.wait()
            assert async_q.empty()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async(queue.async_q))
        queue.close()
        loop.run_until_complete(queue.wait_closed())

    def test_consumer_threads_wait_until_init(self):
        num_of_threads = 5
        items = 6

        total_items = num_of_threads * items

        queue: janus.Queue[Any] = janus.Queue(maxsize=total_items, init_async_part=False)
        barrier = threading.Barrier(num_of_threads + 1)
        start = threading.Event()
        lock = threading.Lock()
        last_exception = []

        def get_something_after_init():
            queue.full_init.wait()
            start.wait()

            while not queue.sync_q.empty():
                with lock:
                    if queue.sync_q.empty():
                        break
                    try:
                        queue.sync_q.get(block=False)
                        queue.sync_q.task_done()
                    except Exception as E:
                        last_exception.append(E)
                        break

            barrier.wait()

        for thr_num in range(num_of_threads):
            self.tpe.submit(get_something_after_init)

        async def init_async(async_q: janus.AsyncQueue[Any]):
            for i in range(total_items):
                await async_q.put(i)

            start.set()
            barrier.wait()

            if last_exception:
                raise last_exception.pop()

            assert async_q.empty()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async(queue.async_q))
        queue.close()
        loop.run_until_complete(queue.wait_closed())

    def test_consumer_concurrent_threads_wait_until_init(self):
        num_of_threads = 6
        items = 7

        total_items = num_of_threads * items

        queue: janus.Queue[Any] = janus.Queue(maxsize=total_items, init_async_part=False)
        barrier = threading.Barrier(num_of_threads + 1)
        start = threading.Event()
        lock = threading.Lock()

        def do_wit_lock(func):
            def wrapper(self):
                with lock:
                    return func(self)
            return wrapper

        counter = type(
            "Counter", (object,),
            {
                "c": 0,
                "get": do_wit_lock(lambda self: self.c),
                "increase": do_wit_lock(lambda self: setattr(self, "c", self.c + 1))
            }
        )()

        def get_something_after_init():
            queue.full_init.wait()
            start.wait()

            while counter.get() < total_items:
                try:
                    queue.sync_q.get(block=False)
                    queue.sync_q.task_done()
                except janus.SyncQueueEmpty:
                    ...

                counter.increase()

            barrier.wait()

        for thr_num in range(num_of_threads):
            self.tpe.submit(get_something_after_init)

        async def init_async(async_q: janus.AsyncQueue[Any]):
            for i in range(total_items):
                await async_q.put(i)

            start.set()
            barrier.wait()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(init_async(queue.async_q))
        queue.close()
        loop.run_until_complete(queue.wait_closed())

    def test_async_producers_sync_consumer(self):
        num_of_producers = 6
        items = 7

        total_items = num_of_producers * items

        queue: janus.Queue[Any] = janus.Queue(maxsize=total_items, init_async_part=False)

        async def producer(async_q: janus.AsyncQueue, prod_num: int):
            for i in range(items):
                await async_q.put((prod_num, i))

        fut = asyncio.gather(
            *(producer(queue.async_q, cor_num) for cor_num in range(num_of_producers))
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(fut)

        actual_count = 0
        while not queue.sync_q.empty():
            queue.sync_q.get()
            queue.sync_q.task_done()
            actual_count += 1

        assert actual_count == total_items

        queue.close()
