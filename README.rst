=====
janus
=====

Mixed sync-async queue, supposed to be used for communicating between
classic synchronous (threaded) code and asynchronous (in terms of
asyncio_) one.

Like Janus_ god the queue object from the library has two faces:
synchronous and asynchronous interface.

Synchronous is fully compatible with `standard queue
<https://docs.python.org/3/library/queue.html>`_, asynchronous one
follows `asyncio queue design
<https://docs.python.org/3/library/asyncio-queue.html>`_.

Usage example
=============

::

    import asyncio
    import janus

    loop = asyncio.get_event_loop()
    queue = janus.Queue(loop=loop)

    def threaded(sync_q):
        for i in range(100):
            sync_q.put(i)
        sync_q.join()

    @asyncio.coroutine
    def async_coro(async_q):

        for i in range(100):
            val = yield from async_q.get()
            assert val == i
            async_q.task_done()


    fut = loop.run_in_executor(None, lambda: threaded(sync_q))
    loop.run_until_complete(async_coro(q.async_q))
    loop.run_until_complete(fut)


License
=======

``janus`` library is offered under Apache 2 license.

Thanks
======

The library development is sponsored by DataRobot (http://datarobot.com/)

.. _Janus: https://en.wikipedia.org/wiki/Janus
.. _asyncio: https://docs.python.org/3/library/asyncio.html
