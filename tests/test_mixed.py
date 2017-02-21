import asyncio
import concurrent.futures
import unittest

from unittest import mock

import janus


class TestMixedMode(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        self.loop.set_default_executor(self.executor)
        asyncio.set_event_loop(None)

    def tearDown(self):
        self.executor.shutdown()
        self.loop.close()

    def test_ctor_loop(self):
        loop = mock.Mock()
        q = janus.Queue(loop=loop)
        self.assertIs(q._loop, loop)

        q = janus.Queue(loop=self.loop)
        self.assertIs(q._loop, self.loop)

    def test_ctor_noloop(self):
        asyncio.set_event_loop(self.loop)
        q = janus.Queue()
        self.assertIs(q._loop, self.loop)

    def test_maxsize(self):
        q = janus.Queue(5, loop=self.loop)
        self.assertIs(5, q.maxsize)

    def test_maxsize_named_param(self):
        q = janus.Queue(maxsize=7, loop=self.loop)
        self.assertIs(7, q.maxsize)

    def test_maxsize_default(self):
        q = janus.Queue(loop=self.loop)
        self.assertIs(0, q.maxsize)

    def test_unfinished(self):
        q = janus.Queue(loop=self.loop)
        self.assertEqual(q.sync_q.unfinished_tasks, 0)
        self.assertEqual(q.async_q.unfinished_tasks, 0)
        q.sync_q.put(1)
        self.assertEqual(q.sync_q.unfinished_tasks, 1)
        self.assertEqual(q.async_q.unfinished_tasks, 1)
        q.sync_q.get()
        self.assertEqual(q.sync_q.unfinished_tasks, 1)
        self.assertEqual(q.async_q.unfinished_tasks, 1)
        q.sync_q.task_done()
        self.assertEqual(q.sync_q.unfinished_tasks, 0)
        self.assertEqual(q.async_q.unfinished_tasks, 0)

    def test_sync_put_async_get(self):
        q = janus.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                q.sync_q.put(i)

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                val = yield from q.async_q.get()
                self.assertEqual(val, i)

            self.assertTrue(q.async_q.empty())

            yield from f

        for i in range(3):
            self.loop.run_until_complete(go())

    def test_async_put_sync_get(self):
        q = janus.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                val = q.sync_q.get()
                self.assertEqual(val, i)

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                yield from q.async_q.put(i)

            yield from f
            self.assertTrue(q.async_q.empty())

        for i in range(3):
            self.loop.run_until_complete(go())

    def test_sync_join_async_done(self):
        q = janus.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                q.sync_q.put(i)
            q.sync_q.join()

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                val = yield from q.async_q.get()
                self.assertEqual(val, i)
                q.async_q.task_done()

            self.assertTrue(q.async_q.empty())

            yield from f

        for i in range(3):
            self.loop.run_until_complete(go())

    def test_async_join_async_done(self):
        q = janus.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                val = q.sync_q.get()
                self.assertEqual(val, i)
                q.sync_q.task_done()

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                yield from q.async_q.put(i)

            yield from q.async_q.join()

            yield from f
            self.assertTrue(q.async_q.empty())

        for i in range(3):
            self.loop.run_until_complete(go())

    def test_wait_without_closing(self):
        q = janus.Queue(loop=self.loop)

        with self.assertRaises(RuntimeError):
            self.loop.run_until_complete(q.wait_closed())

        q.close()
        self.loop.run_until_complete(q.wait_closed())

    def test_modifying_forbidden_after_closing(self):
        q = janus.Queue(loop=self.loop)
        q.close()

        with self.assertRaises(RuntimeError):
            q.sync_q.put(5)

        with self.assertRaises(RuntimeError):
            q.sync_q.get()

        with self.assertRaises(RuntimeError):
            q.sync_q.task_done()

        with self.assertRaises(RuntimeError):
            self.loop.run_until_complete(q.async_q.put(5))

        with self.assertRaises(RuntimeError):
            q.async_q.put_nowait(5)

        with self.assertRaises(RuntimeError):
            q.async_q.get_nowait()

        with self.assertRaises(RuntimeError):
            self.loop.run_until_complete(q.sync_q.task_done())

        self.loop.run_until_complete(q.wait_closed())

    def test_double_closing(self):
        q = janus.Queue(loop=self.loop)
        q.close()
        q.close()
        self.loop.run_until_complete(q.wait_closed())
