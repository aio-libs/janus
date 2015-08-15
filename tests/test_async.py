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

        @asyncio.coroutine
        def add_getter():
            _q = janus.Queue(loop=self.loop)
            q = _q.async_q
            # Start a task that waits to get.
            asyncio.Task(q.get(), loop=self.loop)
            # Let it start waiting.
            yield from asyncio.sleep(0.1, loop=self.loop)
            self.assertTrue('_getters[1]' in fn(q))
            # resume q.get coroutine to finish generator
            q.put_nowait(0)

        self.loop.run_until_complete(add_getter())

        @asyncio.coroutine
        def add_putter():
            _q = janus.Queue(maxsize=1, loop=self.loop)
            q = _q.async_q
            q.put_nowait(1)
            # Start a task that waits to put.
            asyncio.Task(q.put(2), loop=self.loop)
            # Let it start waiting.
            yield from asyncio.sleep(0.1, loop=self.loop)
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

        fut = asyncio.Future(loop=self.loop)

        @asyncio.coroutine
        def putter():
            for i in range(3):
                yield from q.put(i)
                have_been_put.append(i)
                if i == q.maxsize - 1:
                    fut.set_result(None)
            return True

        @asyncio.coroutine
        def test():
            t = asyncio.Task(putter(), loop=self.loop)
            yield from fut

            # The putter is blocked after putting two items.
            self.assertEqual([0, 1], have_been_put)
            self.assertEqual(0, q.get_nowait())

            # Let the putter resume and put last item.
            yield from t
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

        @asyncio.coroutine
        def queue_get():
            return (yield from q.get())

        res = self.loop.run_until_complete(queue_get())
        self.assertEqual(1, res)

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_get_with_putters(self):
        _q = janus.Queue(1, loop=self.loop)
        q = _q.async_q
        q.put_nowait(1)

        fut = asyncio.Future(loop=self.loop)

        @asyncio.coroutine
        def put():
            t = asyncio.async(q.put(2), loop=self.loop)
            yield from asyncio.sleep(0.01, loop=self.loop)
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

        @asyncio.coroutine
        def queue_get():
            nonlocal finished
            started.set()
            res = yield from q.get()
            finished = True
            return res

        @asyncio.coroutine
        def queue_put():
            self.loop.call_later(0.01, q.put_nowait, 1)
            queue_get_task = asyncio.Task(queue_get(), loop=self.loop)
            yield from started.wait()
            self.assertFalse(finished)
            res = yield from queue_get_task
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

        @asyncio.coroutine
        def queue_get():
            return (yield from asyncio.wait_for(q.get(), 0.051,
                                                loop=self.loop))

        @asyncio.coroutine
        def test():
            get_task = asyncio.Task(queue_get(), loop=self.loop)
            yield from asyncio.sleep(0.01,
                                     loop=self.loop)  # let the task start
            q.put_nowait(1)
            return (yield from get_task)

        self.assertEqual(1, self.loop.run_until_complete(test()))

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_get_cancelled_race(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q

        f1 = asyncio.Future(loop=self.loop)

        @asyncio.coroutine
        def g1():
            f1.set_result(None)
            yield from q.get()

        t1 = asyncio.Task(g1(), loop=self.loop)
        t2 = asyncio.Task(q.get(), loop=self.loop)

        self.loop.run_until_complete(f1)
        self.loop.run_until_complete(asyncio.sleep(0.01, loop=self.loop))
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

        asyncio.Task(q.put('a'), loop=self.loop)
        asyncio.Task(q.put('b'), loop=self.loop)

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

        @asyncio.coroutine
        def queue_put():
            # No maxsize, won't block.
            yield from q.put(1)

        self.loop.run_until_complete(queue_put())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_blocking_put_wait(self):
        _q = janus.Queue(maxsize=1, loop=self.loop)
        q = _q.async_q
        started = asyncio.Event(loop=self.loop)
        finished = False

        @asyncio.coroutine
        def queue_put():
            nonlocal finished
            started.set()
            yield from q.put(1)
            yield from q.put(2)
            finished = True

        @asyncio.coroutine
        def queue_get():
            self.loop.call_later(0.01, q.get_nowait)
            queue_put_task = asyncio.Task(queue_put(), loop=self.loop)
            yield from started.wait()
            self.assertFalse(finished)
            yield from queue_put_task
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

        @asyncio.coroutine
        def queue_put():
            yield from q.put(1)
            yield from q.put(2)
            self.assertTrue(q.full())

        self.loop.run_until_complete(queue_put())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_put_cancelled(self):
        _q = janus.Queue(loop=self.loop)
        q = _q.async_q

        @asyncio.coroutine
        def queue_put():
            yield from q.put(1)
            return True

        @asyncio.coroutine
        def test():
            return (yield from q.get())

        t = asyncio.Task(queue_put(), loop=self.loop)
        self.assertEqual(1, self.loop.run_until_complete(test()))
        self.assertTrue(t.done())
        self.assertTrue(t.result())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_put_cancelled_race(self):
        _q = janus.Queue(loop=self.loop, maxsize=1)
        q = _q.async_q

        put_a = asyncio.Task(q.put('a'), loop=self.loop)
        put_b = asyncio.Task(q.put('b'), loop=self.loop)
        put_c = asyncio.Task(q.put('X'), loop=self.loop)

        self.loop.run_until_complete(put_a)
        self.assertFalse(put_b.done())

        put_c.cancel()

        with self.assertRaises(asyncio.CancelledError):
            self.loop.run_until_complete(put_c)

        @asyncio.coroutine
        def go():
            a = yield from q.get()
            self.assertEqual(a, 'a')
            b = yield from q.get()
            self.assertEqual(b, 'b')
            self.assertTrue(put_b.done())

        self.loop.run_until_complete(go())

        self.assertFalse(_q._sync_mutex.locked())
        _q.close()
        self.loop.run_until_complete(_q.wait_closed())

    def test_put_with_waiting_getters(self):
        fut = asyncio.Future(loop=self.loop)

        @asyncio.coroutine
        def go():
            fut.set_result(None)
            ret = yield from q.get()
            return ret

        @asyncio.coroutine
        def put():
            yield from q.put('a')

        _q = janus.Queue(loop=self.loop)
        q = _q.async_q
        t = asyncio.Task(go(), loop=self.loop)
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

        @asyncio.coroutine
        def worker():
            nonlocal accumulator

            while running:
                item = yield from q.get()
                accumulator += item
                q.task_done()

        @asyncio.coroutine
        def test():
            tasks = [asyncio.Task(worker(),
                                  loop=self.loop) for index in range(2)]

            yield from q.join()
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

        @asyncio.coroutine
        def join():
            yield from q.join()
            yield from q.join()

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
