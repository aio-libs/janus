import asyncio
import sys
import unittest

import janus
import pytest


class TestMixedMode(unittest.TestCase):

    @pytest.mark.skipif(
        sys.version_info < (3, 7),
        reason="forbidding implicit loop creation works on "
               "Python 3.7 or higher only",
    )
    def test_ctor_noloop(self):
        with self.assertRaises(RuntimeError):
            janus.Queue()

    @pytest.mark.asyncio
    async def test_maxsize(self):
        q = janus.Queue(5)
        self.assertIs(5, q.maxsize)

    @pytest.mark.asyncio
    async def test_maxsize_named_param(self):
        q = janus.Queue(maxsize=7)
        self.assertIs(7, q.maxsize)

    @pytest.mark.asyncio
    async def test_maxsize_default(self):
        q = janus.Queue()
        self.assertIs(0, q.maxsize)

    @pytest.mark.asyncio
    async def test_unfinished(self):
        q = janus.Queue()
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
        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_sync_put_async_get(self):
        loop = janus.current_loop()
        q = janus.Queue()

        def threaded():
            for i in range(5):
                q.sync_q.put(i)

        async def go():
            f = loop.run_in_executor(None, threaded)
            for i in range(5):
                val = await q.async_q.get()
                self.assertEqual(val, i)

            self.assertTrue(q.async_q.empty())

            await f

        for i in range(3):
            await go()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_sync_put_async_join(self):
        loop = janus.current_loop()
        q = janus.Queue()

        for i in range(5):
            q.sync_q.put(i)

        async def do_work():
            await asyncio.sleep(1)
            while True:
                await q.async_q.get()
                q.async_q.task_done()

        task = loop.create_task(do_work())

        async def wait_for_empty_queue():
            await q.async_q.join()
            task.cancel()

        await wait_for_empty_queue()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_async_put_sync_get(self):
        loop = janus.current_loop()
        q = janus.Queue()

        def threaded():
            for i in range(5):
                val = q.sync_q.get()
                self.assertEqual(val, i)

        async def go():
            f = loop.run_in_executor(None, threaded)
            for i in range(5):
                await q.async_q.put(i)

            await f
            self.assertTrue(q.async_q.empty())

        for i in range(3):
            await go()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_sync_join_async_done(self):
        loop = janus.current_loop()
        q = janus.Queue()

        def threaded():
            for i in range(5):
                q.sync_q.put(i)
            q.sync_q.join()

        async def go():
            f = loop.run_in_executor(None, threaded)
            for i in range(5):
                val = await q.async_q.get()
                self.assertEqual(val, i)
                q.async_q.task_done()

            self.assertTrue(q.async_q.empty())

            await f

        for i in range(3):
            await go()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_async_join_async_done(self):
        loop = janus.current_loop()
        q = janus.Queue()

        def threaded():
            for i in range(5):
                val = q.sync_q.get()
                self.assertEqual(val, i)
                q.sync_q.task_done()

        async def go():
            f = loop.run_in_executor(None, threaded)
            for i in range(5):
                await q.async_q.put(i)

            await q.async_q.join()

            await f
            self.assertTrue(q.async_q.empty())

        for i in range(3):
            await go()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_wait_without_closing(self):
        q = janus.Queue()

        with self.assertRaises(RuntimeError):
            await q.wait_closed()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_modifying_forbidden_after_closing(self):
        q = janus.Queue()
        q.close()

        with self.assertRaises(RuntimeError):
            q.sync_q.put(5)

        with self.assertRaises(RuntimeError):
            q.sync_q.get()

        with self.assertRaises(RuntimeError):
            q.sync_q.task_done()

        with self.assertRaises(RuntimeError):
            await q.async_q.put(5)

        with self.assertRaises(RuntimeError):
            q.async_q.put_nowait(5)

        with self.assertRaises(RuntimeError):
            q.async_q.get_nowait()

        with self.assertRaises(RuntimeError):
            await q.sync_q.task_done()

        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_double_closing(self):
        q = janus.Queue()
        q.close()
        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_closed(self):
        q = janus.Queue()
        self.assertFalse(q.closed)
        self.assertFalse(q.async_q.closed)
        self.assertFalse(q.sync_q.closed)
        q.close()
        self.assertTrue(q.closed)
        self.assertTrue(q.async_q.closed)
        self.assertTrue(q.sync_q.closed)
