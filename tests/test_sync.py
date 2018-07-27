# Some simple queue module tests, plus some failure conditions
# to ensure the Queue locks remain stable.
import asyncio
import concurrent.futures
import queue
import time
import unittest
from unittest.mock import patch

import threading

import janus

QUEUE_SIZE = 5


def qfull(q):
    return q._parent._maxsize > 0 and q.qsize() == q._parent._maxsize


# A thread to run a function that unclogs a blocked Queue.
class _TriggerThread(threading.Thread):
    def __init__(self, fn, args):
        self.fn = fn
        self.args = args
        self.startedEvent = threading.Event()
        threading.Thread.__init__(self)

    def run(self):
        # The sleep isn't necessary, but is intended to give the blocking
        # function in the main thread a chance at actually blocking before
        # we unclog it.  But if the sleep is longer than the timeout-based
        # tests wait in their blocking functions, those tests will fail.
        # So we give them much longer timeout values compared to the
        # sleep here (I aimed at 10 seconds for blocking functions --
        # they should never actually wait that long - they should make
        # progress as soon as we call self.fn()).
        time.sleep(0.1)
        self.startedEvent.set()
        self.fn(*self.args)

# Execute a function that blocks, and in a separate thread, a function that
# triggers the release.  Returns the result of the blocking function.  Caution:
# block_func must guarantee to block until trigger_func is called, and
# trigger_func must guarantee to change queue state so that block_func can make
# enough progress to return.  In particular, a block_func that just raises an
# exception regardless of whether trigger_func is called will lead to
# timing-dependent sporadic failures, and one of those went rarely seen but
# undiagnosed for years.  Now block_func must be unexceptional.  If block_func
# is supposed to raise an exception, call do_exceptional_blocking_test()
# instead.


class BlockingTestMixin:
    def setUp(self):
        asyncio.set_event_loop(None)
        self.loop = asyncio.new_event_loop()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        self.loop.set_default_executor(self.executor)

    def tearDown(self):
        self.t = None
        self.executor.shutdown()
        self.loop.close()

    def do_blocking_test(self, block_func, block_args, trigger_func,
                         trigger_args):
        self.t = _TriggerThread(trigger_func, trigger_args)
        self.t.start()
        self.result = block_func(*block_args)
        # If block_func returned before our thread made the call, we failed!
        if not self.t.startedEvent.is_set():
            self.fail("blocking function '%r' appeared not to block" %
                      block_func)
        self.t.join(10)  # make sure the thread terminates
        if self.t.is_alive():
            self.fail("trigger function '%r' appeared to not return" %
                      trigger_func)
        return self.result

    # Call this instead if block_func is supposed to raise an exception.
    def do_exceptional_blocking_test(self, block_func, block_args,
                                     trigger_func, trigger_args,
                                     expected_exception_class):
        self.t = _TriggerThread(trigger_func, trigger_args)
        self.t.start()
        try:
            try:
                block_func(*block_args)
            except expected_exception_class:
                raise
            else:
                self.fail("expected exception of kind %r" %
                          expected_exception_class)
        finally:
            self.t.join(10)  # make sure the thread terminates
            if self.t.is_alive():
                self.fail("trigger function '%r' appeared to not return" %
                          trigger_func)
            if not self.t.startedEvent.is_set():
                self.fail("trigger thread ended but event never set")


class BaseQueueTestMixin(BlockingTestMixin):
    def setUp(self):
        self.cum = 0
        self.cumlock = threading.Lock()
        super().setUp()

    def simple_queue_test(self, _q):
        q = _q.sync_q
        if q.qsize():
            raise RuntimeError("Call this function with an empty queue")
        self.assertTrue(q.empty())
        self.assertFalse(q.full())
        # I guess we better check things actually queue correctly a little :)
        q.put(111)
        q.put(333)
        q.put(222)
        target_order = dict(Queue=[111, 333, 222],
                            LifoQueue=[222, 333, 111],
                            PriorityQueue=[111, 222, 333])
        actual_order = [q.get(), q.get(), q.get()]
        self.assertEqual(actual_order, target_order[_q.__class__.__name__],
                         "Didn't seem to queue the correct data!")
        for i in range(QUEUE_SIZE - 1):
            q.put(i)
            self.assertTrue(q.qsize(), "Queue should not be empty")
        self.assertTrue(not qfull(q), "Queue should not be full")
        last = 2 * QUEUE_SIZE
        full = 3 * 2 * QUEUE_SIZE
        q.put(last)
        self.assertTrue(qfull(q), "Queue should be full")
        self.assertFalse(q.empty())
        self.assertTrue(q.full())
        try:
            q.put(full, block=0)
            self.fail("Didn't appear to block with a full queue")
        except queue.Full:
            pass
        try:
            q.put(full, timeout=0.01)
            self.fail("Didn't appear to time-out with a full queue")
        except queue.Full:
            pass
        # Test a blocking put
        self.do_blocking_test(q.put, (full, ), q.get, ())
        self.do_blocking_test(q.put, (full, True, 10), q.get, ())
        # Empty it
        for i in range(QUEUE_SIZE):
            q.get()
        self.assertTrue(not q.qsize(), "Queue should be empty")
        try:
            q.get(block=0)
            self.fail("Didn't appear to block with an empty queue")
        except queue.Empty:
            pass
        try:
            q.get(timeout=0.01)
            self.fail("Didn't appear to time-out with an empty queue")
        except queue.Empty:
            pass
        # Test a blocking get
        self.do_blocking_test(q.get, (), q.put, ('empty', ))
        self.do_blocking_test(q.get, (True, 10), q.put, ('empty', ))

    def worker(self, q):
        while True:
            x = q.get()
            if x < 0:
                q.task_done()
                return
            with self.cumlock:
                self.cum += x
            q.task_done()

    def queue_join_test(self, q):
        self.cum = 0
        for i in (0, 1):
            threading.Thread(target=self.worker, args=(q, )).start()
        for i in range(100):
            q.put(i)
        q.join()
        self.assertEqual(self.cum, sum(range(100)),
                         "q.join() did not block until all tasks were done")
        for i in (0, 1):
            q.put(-1)  # instruct the threads to close
        q.join()  # verify that you can join twice

    def test_queue_task_done(self):
        # Test to make sure a queue task completed successfully.
        q = self.type2test(loop=self.loop).sync_q
        try:
            q.task_done()
        except ValueError:
            pass
        else:
            self.fail("Did not detect task count going negative")

    def test_queue_join(self):
        # Test that a queue join()s successfully, and before anything else
        # (done twice for insurance).
        q = self.type2test(loop=self.loop).sync_q
        self.queue_join_test(q)
        self.queue_join_test(q)
        try:
            q.task_done()
        except ValueError:
            pass
        else:
            self.fail("Did not detect task count going negative")

    def test_simple_queue(self):
        # Do it a couple of times on the same queue.
        # Done twice to make sure works with same instance reused.
        q = self.type2test(QUEUE_SIZE, loop=self.loop)
        self.simple_queue_test(q)
        self.simple_queue_test(q)

    def test_negative_timeout_raises_exception(self):
        q = self.type2test(QUEUE_SIZE, loop=self.loop).sync_q
        with self.assertRaises(ValueError):
            q.put(1, timeout=-1)
        with self.assertRaises(ValueError):
            q.get(1, timeout=-1)

    def test_nowait(self):
        q = self.type2test(QUEUE_SIZE, loop=self.loop).sync_q
        for i in range(QUEUE_SIZE):
            q.put_nowait(1)
        with self.assertRaises(queue.Full):
            q.put_nowait(1)

        for i in range(QUEUE_SIZE):
            q.get_nowait()
        with self.assertRaises(queue.Empty):
            q.get_nowait()

    def test_shrinking_queue(self):
        # issue 10110
        q = self.type2test(3, loop=self.loop).sync_q
        q.put(1)
        q.put(2)
        q.put(3)
        with self.assertRaises(queue.Full):
            q.put_nowait(4)
        self.assertEqual(q.qsize(), 3)
        q._maxsize = 2  # shrink the queue
        with self.assertRaises(queue.Full):
            q.put_nowait(4)

    def test_maxsize(self):
        # Test to make sure a queue task completed successfully.
        q = self.type2test(maxsize=5, loop=self.loop).sync_q
        self.assertEqual(q.maxsize, 5)


class QueueTest(BaseQueueTestMixin, unittest.TestCase):
    type2test = janus.Queue


class LifoQueueTest(BaseQueueTestMixin, unittest.TestCase):
    type2test = janus.LifoQueue


class PriorityQueueTest(BaseQueueTestMixin, unittest.TestCase):
    type2test = janus.PriorityQueue


# A Queue subclass that can provoke failure at a moment's notice :)
class FailingQueueException(Exception):
    pass


class FailingQueue(janus.Queue):
    def __init__(self, *args, **kwargs):
        self.fail_next_put = False
        self.fail_next_get = False
        super().__init__(*args, **kwargs)

    def _put(self, item):
        if self.fail_next_put:
            self.fail_next_put = False
            raise FailingQueueException("You Lose")
        return super()._put(item)

    def _get(self):
        if self.fail_next_get:
            self.fail_next_get = False
            raise FailingQueueException("You Lose")
        return super()._get()


class FailingQueueTest(BlockingTestMixin, unittest.TestCase):
    def failing_queue_test(self, _q):
        q = _q.sync_q
        if q.qsize():
            raise RuntimeError("Call this function with an empty queue")
        for i in range(QUEUE_SIZE - 1):
            q.put(i)
        # Test a failing non-blocking put.
        _q.fail_next_put = True
        try:
            q.put("oops", block=0)
            self.fail("The queue didn't fail when it should have")
        except FailingQueueException:
            pass
        _q.fail_next_put = True
        try:
            q.put("oops", timeout=0.1)
            self.fail("The queue didn't fail when it should have")
        except FailingQueueException:
            pass
        q.put("last")
        self.assertTrue(qfull(q), "Queue should be full")
        # Test a failing blocking put
        _q.fail_next_put = True
        try:
            self.do_blocking_test(q.put, ("full", ), q.get, ())
            self.fail("The queue didn't fail when it should have")
        except FailingQueueException:
            pass
        # Check the Queue isn't damaged.
        # put failed, but get succeeded - re-add
        q.put("last")
        # Test a failing timeout put
        _q.fail_next_put = True
        try:
            self.do_exceptional_blocking_test(q.put, ("full", True, 10),
                                              q.get, (), FailingQueueException)
            self.fail("The queue didn't fail when it should have")
        except FailingQueueException:
            pass
        # Check the Queue isn't damaged.
        # put failed, but get succeeded - re-add
        q.put("last")
        self.assertTrue(qfull(q), "Queue should be full")
        q.get()
        self.assertTrue(not qfull(q), "Queue should not be full")
        q.put("last")
        self.assertTrue(qfull(q), "Queue should be full")
        # Test a blocking put
        self.do_blocking_test(q.put, ("full", ), q.get, ())
        # Empty it
        for i in range(QUEUE_SIZE):
            q.get()
        self.assertTrue(not q.qsize(), "Queue should be empty")
        q.put("first")
        _q.fail_next_get = True
        try:
            q.get()
            self.fail("The queue didn't fail when it should have")
        except FailingQueueException:
            pass
        self.assertTrue(q.qsize(), "Queue should not be empty")
        _q.fail_next_get = True
        try:
            q.get(timeout=0.1)
            self.fail("The queue didn't fail when it should have")
        except FailingQueueException:
            pass
        self.assertTrue(q.qsize(), "Queue should not be empty")
        q.get()
        self.assertTrue(not q.qsize(), "Queue should be empty")
        _q.fail_next_get = True
        try:
            self.do_exceptional_blocking_test(q.get, (), q.put, ('empty', ),
                                              FailingQueueException)
            self.fail("The queue didn't fail when it should have")
        except FailingQueueException:
            pass
        # put succeeded, but get failed.
        self.assertTrue(q.qsize(), "Queue should not be empty")
        q.get()
        self.assertTrue(not q.qsize(), "Queue should be empty")

    def test_failing_queue(self):
        # Test to make sure a queue is functioning correctly.
        # Done twice to the same instance.
        q = FailingQueue(QUEUE_SIZE, loop=self.loop)
        self.failing_queue_test(q)
        self.failing_queue_test(q)

    def test_closed_loop_non_failing(self):
        q = janus.Queue(QUEUE_SIZE, loop=self.loop).sync_q
        # we are pacthing loop to follow setUp/tearDown agreement
        with patch.object(self.loop, 'call_soon_threadsafe') as func:
            func.side_effect = RuntimeError()
            q.put_nowait(1)
            self.assertEqual(func.call_count, 1)


if __name__ == "__main__":
    unittest.main()
