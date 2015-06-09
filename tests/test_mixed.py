import asyncio
import unittest

from unittest import mock

import mixedqueue


class TestMixedMode(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

    def tearDown(self):
        self.loop.close()

    def test_ctor_loop(self):
        loop = mock.Mock()
        q = mixedqueue.Queue(loop=loop)
        self.assertIs(q._loop, loop)

        q = mixedqueue.Queue(loop=self.loop)
        self.assertIs(q._loop, self.loop)

    def test_ctor_noloop(self):
        asyncio.set_event_loop(self.loop)
        q = mixedqueue.Queue()
        self.assertIs(q._loop, self.loop)

    def test_maxsize(self):
        q = mixedqueue.Queue(5, loop=self.loop)
        self.assertIs(5, q.maxsize)

    def test_maxsize_named_param(self):
        q = mixedqueue.Queue(maxsize=7, loop=self.loop)
        self.assertIs(7, q.maxsize)

    def test_maxsize_default(self):
        q = mixedqueue.Queue(loop=self.loop)
        self.assertIs(0, q.maxsize)

    def test_sync_put_async_get(self):
        q = mixedqueue.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                q.sync_queue.put(i)

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                val = yield from q.async_queue.get()
                self.assertEqual(val, i)

            self.assertTrue(q.async_queue.empty())

            yield from f

        for i in range(3):
            self.loop.run_until_complete(go())

    def test_async_put_sync_get(self):
        q = mixedqueue.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                val = q.sync_queue.get()
                self.assertEqual(val, i)

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                yield from q.async_queue.put(i)

            yield from f
            self.assertTrue(q.async_queue.empty())

        for i in range(3):
            self.loop.run_until_complete(go())

    def xtest_sync_join_async_done(self):
        q = mixedqueue.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                q.sync_queue.put(i)

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                val = yield from q.async_queue.get()
                self.assertEqual(val, i)

            self.assertTrue(q.async_queue.empty())

            yield from f

        for i in range(3):
            self.loop.run_until_complete(go())

    def xtest_async_join_sync_done(self):
        q = mixedqueue.Queue(loop=self.loop)

        def threaded():
            for i in range(5):
                q.sync_queue.put(i)

        @asyncio.coroutine
        def go():
            f = self.loop.run_in_executor(None, threaded)
            for i in range(5):
                val = yield from q.async_queue.get()
                self.assertEqual(val, i)

            self.assertTrue(q.async_queue.empty())

            yield from f

        for i in range(3):
            self.loop.run_until_complete(go())
