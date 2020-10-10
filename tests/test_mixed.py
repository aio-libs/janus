import asyncio
import sys

import pytest

import janus


class TestMixedMode:
    @pytest.mark.skipif(
        sys.version_info < (3, 7),
        reason="forbidding implicit loop creation works on "
        "Python 3.7 or higher only",
    )
    def test_ctor_noloop(self):
        with pytest.raises(RuntimeError):
            janus.Queue()

    @pytest.mark.asyncio
    async def test_maxsize(self):
        q = janus.Queue(5)
        assert 5 == q.maxsize

    @pytest.mark.asyncio
    async def test_maxsize_named_param(self):
        q = janus.Queue(maxsize=7)
        assert 7 == q.maxsize

    @pytest.mark.asyncio
    async def test_maxsize_default(self):
        q = janus.Queue()
        assert 0 == q.maxsize

    @pytest.mark.asyncio
    async def test_unfinished(self):
        q = janus.Queue()
        assert q.sync_q.unfinished_tasks == 0
        assert q.async_q.unfinished_tasks == 0
        q.sync_q.put(1)
        assert q.sync_q.unfinished_tasks == 1
        assert q.async_q.unfinished_tasks == 1
        q.sync_q.get()
        assert q.sync_q.unfinished_tasks == 1
        assert q.async_q.unfinished_tasks == 1
        q.sync_q.task_done()
        assert q.sync_q.unfinished_tasks == 0
        assert q.async_q.unfinished_tasks == 0
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
                assert val == i

            assert q.async_q.empty()

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
                assert val == i

        async def go():
            f = loop.run_in_executor(None, threaded)
            for i in range(5):
                await q.async_q.put(i)

            await f
            assert q.async_q.empty()

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
                assert val == i
                q.async_q.task_done()

            assert q.async_q.empty()

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
                assert val == i
                q.sync_q.task_done()

        async def go():
            f = loop.run_in_executor(None, threaded)
            for i in range(5):
                await q.async_q.put(i)

            await q.async_q.join()

            await f
            assert q.async_q.empty()

        for i in range(3):
            await go()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_wait_without_closing(self):
        q = janus.Queue()

        with pytest.raises(RuntimeError):
            await q.wait_closed()

        q.close()
        await q.wait_closed()

    @pytest.mark.asyncio
    async def test_modifying_forbidden_after_closing(self):
        q = janus.Queue()
        q.close()

        with pytest.raises(RuntimeError):
            q.sync_q.put(5)

        with pytest.raises(RuntimeError):
            q.sync_q.get()

        with pytest.raises(RuntimeError):
            q.sync_q.task_done()

        with pytest.raises(RuntimeError):
            await q.async_q.put(5)

        with pytest.raises(RuntimeError):
            q.async_q.put_nowait(5)

        with pytest.raises(RuntimeError):
            q.async_q.get_nowait()

        with pytest.raises(RuntimeError):
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
        assert not q.closed
        assert not q.async_q.closed
        assert not q.sync_q.closed
        q.close()
        assert q.closed
        assert q.async_q.closed
        assert q.sync_q.closed
