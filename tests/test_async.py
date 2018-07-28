"""Tests for queues.py"""

import asyncio
import concurrent.futures
import unittest

import janus


class _QueueTestBase(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        self.loop.set_default_executor(self.executor)
        asyncio.set_event_loop(None)

    def tearDown(self):
        self.executor.shutdown()
        self.loop.close()


class QueueBasicTests(_QueueTestBase):
    def _test_repr_or_str(self, fn, expect_id):
        """Test Queue's repr or str.

        fn is repr or str. expect_id is True if we expect the Queue's id to
        appear in fn(Queue()).
        """

        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        self.assertTrue(fn(q).startswith('<Queue'), fn(q))
        id_is_present = hex(id(q)) in fn(q)
        self.assertEqual(expect_id, id_is_present)

        async def add_getter():
            _q = janus.Queue(loop=self.loop)
            q = _q.async_q
            # Start a task that waits to get.
            self.loop.create_task(q.get())
            # Let it start waiting.
            await asyncio.sleep(0.1)
            self.assertTrue('_getters[1]' in fn(q))
            # resume q.get coroutine to finish generator
            q.put_nowait(0)

        self.loop.run_until_complete(add_getter())

        async def add_putter():
            _q = janus.Queue(maxsize=1, loop=self.loop)
            q = _q.async_q
            q.put_nowait(1)
            # Start a task that waits to put.
            self.loop.create_task(q.put(2))
            # Let it start waiting.
            await asyncio.sleep(0.1)
            self.assertTrue('_putters[1]' in fn(q))
            # resume q.put coroutine to finish generator
            q.get_nowait()

        self.loop.run_until_complete(add_putter())

        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)
        self.assertTrue('_queue=[1]' in fn(q))

    # def test_repr(self):
    #     self._test_repr_or_str(repr, True)

    # def test_str(self):
    #     self._test_repr_or_str(str, False)

    def test_empty(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        self.assertTrue(q.empty())
        q.put_nowait(1)
        self.assertFalse(q.empty())
        self.assertEqual(1, q.get_nowait())
        self.assertTrue(q.empty())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_full(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        self.assertFalse(q.full())

        _q = janus.Queue(maxsize=1, loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)
        self.assertTrue(q.full())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_order(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        for i in [1, 3, 2]:
            q.put_nowait(i)

        items = [q.get_nowait() for _ in range(3)]
        self.assertEqual([1, 3, 2], items)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_maxsize(self):
        _q = janus.Queue(maxsize=2, loop=self.loop)
        q = _q.async_q
        self.assertEqual(2, q.maxsize)
        have_been_put = []

        fut = self.loop.create_future()

        async def putter():
            for i in range(3):
                await q.put(i)
                have_been_put.append(i)
                if i == q.maxsize - 1:
                    fut.set_result(None)
            return True

        async def test():
            t = self.loop.create_task(putter())
            await fut

            # The putter is blocked after putting two items.
            self.assertEqual([0, 1], have_been_put)
            self.assertEqual(0, q.get_nowait())

            # Let the putter resume and put last item.
            await t
            self.assertEqual([0, 1, 2], have_been_put)
            self.assertEqual(1, q.get_nowait())
            self.assertEqual(2, q.get_nowait())

        self.loop.run_until_complete(test())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())


class QueueGetTests(_QueueTestBase):
    def test_blocking_get(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)

        async def queue_get():
            return (await q.get())

        res = self.loop.run_until_complete(queue_get())
        self.assertEqual(1, res)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_get_with_putters(self):
        _q = janus.Queue(1, loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)

        fut = self.loop.create_future()

        async def put():
            t = janus.ensure_future(q.put(2), loop=self.loop)
            await asyncio.sleep(0.01)
            fut.set_result(None)
            return t

        t = self.loop.run_until_complete(put())

        res = self.loop.run_until_complete(q.get())
        self.assertEqual(1, res)

        self.loop.run_until_complete(t)
        self.assertEqual(1, q.qsize())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_blocking_get_wait(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        started = asyncio.Event(loop=self.loop)
        finished = False

        async def queue_get():
            nonlocal finished
            started.set()
            res = await q.get()
            finished = True
            return res

        async def queue_put():
            self.loop.call_later(0.01, q.put_nowait, 1)
            queue_get_task = self.loop.create_task(queue_get())
            await started.wait()
            self.assertFalse(finished)
            res = await queue_get_task
            self.assertTrue(finished)
            return res

        res = self.loop.run_until_complete(queue_put())
        self.assertEqual(1, res)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_nonblocking_get(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)
        self.assertEqual(1, q.get_nowait())

        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_nonblocking_get_exception(self):
        _q = janus.Queue(loop=self.loop)
        self.assertRaises(asyncio.QueueEmpty, _q.async_q.get_nowait)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_get_cancelled(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q

        async def queue_get():
            return await asyncio.wait_for(q.get(), 0.051)

        async def test():
            get_task = self.loop.create_task(queue_get())
            await asyncio.sleep(0.01)  # let the task start
            q.put_nowait(1)
            return await get_task

        self.assertEqual(1, self.loop.run_until_complete(test()))

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_get_cancelled_race(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q

        f1 = self.loop.create_future()

        async def g1():
            f1.set_result(None)
            await q.get()

        t1 = self.loop.create_task(g1())
        t2 = self.loop.create_task(q.get())

        self.loop.run_until_complete(f1)
        self.loop.run_until_complete(asyncio.sleep(0.01))
        t1.cancel()

        with self.assertRaises(asyncio.CancelledError):
            self.loop.run_until_complete(t1)
        self.assertTrue(t1.done())
        q.put_nowait('a')

        self.loop.run_until_complete(t2)
        self.assertEqual(t2.result(), 'a')

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_get_with_waiting_putters(self):
        _q = janus.Queue(loop=self.loop, maxsize=1)
        q = _q.async_q

        self.loop.create_task(q.put('a'))
        self.loop.create_task(q.put('b'))

        self.loop.run_until_complete(asyncio.sleep(0.01, loop=self.loop))

        self.assertEqual(self.loop.run_until_complete(q.get()), 'a')
        self.assertEqual(self.loop.run_until_complete(q.get()), 'b')

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())


class QueuePutTests(_QueueTestBase):
    def test_blocking_put(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q

        async def queue_put():
            # No maxsize, won't block.
            await q.put(1)

        self.loop.run_until_complete(queue_put())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_blocking_put_wait(self):
        _q = janus.Queue(maxsize=1, loop=self.loop)
        q = _q.async_q
        started = asyncio.Event(loop=self.loop)
        finished = False

        async def queue_put():
            nonlocal finished
            started.set()
            await q.put(1)
            await q.put(2)
            finished = True

        async def queue_get():
            self.loop.call_later(0.01, q.get_nowait)
            queue_put_task = self.loop.create_task(queue_put())
            await started.wait()
            self.assertFalse(finished)
            await queue_put_task
            self.assertTrue(finished)

        self.loop.run_until_complete(queue_get())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_nonblocking_put(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)
        self.assertEqual(1, q.get_nowait())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_nonblocking_put_exception(self):
        _q = janus.Queue(maxsize=1, loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)
        self.assertRaises(asyncio.QueueFull, q.put_nowait, 2)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_float_maxsize(self):
        _q = janus.Queue(maxsize=1.3, loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)
        q.put_nowait(2)
        self.assertTrue(q.full())
        self.assertRaises(asyncio.QueueFull, q.put_nowait, 3)

        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

        _q = janus.Queue(maxsize=1.3, loop=self.loop)
        q = _q.async_q

        async def queue_put():
            await q.put(1)
            await q.put(2)
            self.assertTrue(q.full())

        self.loop.run_until_complete(queue_put())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_put_cancelled(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q

        async def queue_put():
            await q.put(1)
            return True

        async def test():
            return (await q.get())

        t = self.loop.create_task(queue_put())
        self.assertEqual(1, self.loop.run_until_complete(test()))
        self.assertTrue(t.done())
        self.assertTrue(t.result())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_put_cancelled_race(self):
        _q = janus.Queue(loop=self.loop, maxsize=1)
        q = _q.async_q

        put_a = self.loop.create_task(q.put('a'))
        put_b = self.loop.create_task(q.put('b'))
        put_c = self.loop.create_task(q.put('X'))

        self.loop.run_until_complete(put_a)
        self.assertFalse(put_b.done())

        put_c.cancel()

        with self.assertRaises(asyncio.CancelledError):
            self.loop.run_until_complete(put_c)

        async def go():
            a = await q.get()
            self.assertEqual(a, 'a')
            b = await q.get()
            self.assertEqual(b, 'b')
            self.assertTrue(put_b.done())

        self.loop.run_until_complete(go())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_put_with_waiting_getters(self):
        fut = self.loop.create_future()

        async def go():
            fut.set_result(None)
            ret = await q.get()
            return ret

        async def put():
            await q.put('a')

        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        t = self.loop.create_task(go())
        self.loop.run_until_complete(fut)
        self.loop.run_until_complete(put())
        self.assertEqual(self.loop.run_until_complete(t), 'a')

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())


class LifoQueueTests(_QueueTestBase):
    def test_order(self):
        _q = janus.LifoQueue(loop=self.loop)
        q = _q.async_q
        for i in [1, 3, 2]:
            q.put_nowait(i)

        items = [q.get_nowait() for _ in range(3)]
        self.assertEqual([2, 3, 1], items)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())


class PriorityQueueTests(_QueueTestBase):
    def test_order(self):
        _q = janus.PriorityQueue(loop=self.loop)
        q = _q.async_q
        for i in [1, 3, 2]:
            q.put_nowait(i)

        items = [q.get_nowait() for _ in range(3)]
        self.assertEqual([1, 2, 3], items)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())


class _QueueJoinTestMixin:

    q_class = None

    def test_task_done_underflow(self):
        _q = self.q_class(loop=self.loop)
        q = _q.async_q
        self.assertRaises(ValueError, q.task_done)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_task_done(self):
        _q = self.q_class(loop=self.loop)
        q = _q.async_q
        for i in range(100):
            q.put_nowait(i)

        accumulator = 0

        # Two workers get items from the queue and call task_done after each.
        # Join the queue and assert all items have been processed.
        running = True

        async def worker():
            nonlocal accumulator

            while running:
                item = await q.get()
                accumulator += item
                q.task_done()

        async def test():
            tasks = [self.loop.create_task(worker())
                     for index in range(2)]

            await q.join()
            return tasks

        tasks = self.loop.run_until_complete(test())
        self.assertEqual(sum(range(100)), accumulator)

        # close running generators
        running = False
        for i in range(len(tasks)):
            q.put_nowait(0)
        self.loop.run_until_complete(asyncio.wait(tasks, loop=self.loop))

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_join_empty_queue(self):
        _q = self.q_class(loop=self.loop)
        q = _q.async_q

        # Test that a queue join()s successfully, and before anything else
        # (done twice for insurance).

        async def join():
            await q.join()
            await q.join()

        self.loop.run_until_complete(join())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    @unittest.expectedFailure
    def test_format(self):
        _q = self.q_class(loop=self.loop)
        q = _q.async_q
        self.assertEqual(q._format(), 'maxsize=0')

        q._unfinished_tasks = 2
        self.assertEqual(q._format(), 'maxsize=0 tasks=2')

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())


class QueueJoinTests(_QueueJoinTestMixin, _QueueTestBase):
    q_class = janus.Queue


class LifoQueueJoinTests(_QueueJoinTestMixin, _QueueTestBase):
    q_class = janus.LifoQueue


class PriorityQueueJoinTests(_QueueJoinTestMixin, _QueueTestBase):
    q_class = janus.PriorityQueue
