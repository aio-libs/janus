import asyncio
import logging
import threading
from asyncio import QueueEmpty as AsyncQueueEmpty
from asyncio import QueueFull as AsyncQueueFull
from collections import deque
from heapq import heappop, heappush
from queue import Empty as SyncQueueEmpty
from queue import Full as SyncQueueFull

__version__ = '0.4.0'

log = logging.getLogger(__package__)


try:
    ensure_future = asyncio.ensure_future
except AttributeError:
    ensure_future = getattr(asyncio, 'async')


class Queue:
    def __init__(self, maxsize=0, *, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self._loop = loop
        self._maxsize = maxsize

        self._init(maxsize)

        self._unfinished_tasks = 0

        self._sync_mutex = threading.Lock()
        self._sync_not_empty = threading.Condition(self._sync_mutex)
        self._sync_not_full = threading.Condition(self._sync_mutex)
        self._all_tasks_done = threading.Condition(self._sync_mutex)

        self._async_mutex = asyncio.Lock(loop=loop)
        self._async_not_empty = asyncio.Condition(self._async_mutex, loop=loop)
        self._async_not_full = asyncio.Condition(self._async_mutex, loop=loop)
        self._finished = asyncio.Event(loop=self._loop)
        self._finished.set()

        self._closing = False
        self._pending = set()

        def checked_call_soon_threadsafe(callback, *args):
            try:
                loop.call_soon_threadsafe(callback, *args)
            except RuntimeError:
                # swallowing agreed in #2
                pass
        self._call_soon_threadsafe = checked_call_soon_threadsafe

        def checked_call_soon(callback, *args):
            if not loop.is_closed():
                loop.call_soon(callback, *args)
        self._call_soon = checked_call_soon

        self._sync_queue = _SyncQueueProxy(self)
        self._async_queue = _AsyncQueueProxy(self)

    def close(self):
        with self._sync_mutex:
            self._closing = True
            for fut in self._pending:
                fut.cancel()

    async def wait_closed(self):
        # should be called from loop after close().
        # Nobody should put/get at this point,
        # so lock acquiring is not required
        if not self._closing:
            raise RuntimeError("Waiting for non-closed queue")
        if not self._pending:
            return
        await asyncio.wait(self._pending, loop=self._loop)

    @property
    def closed(self):
        return self._closing and not self._pending

    @property
    def maxsize(self):
        return self._maxsize

    @property
    def sync_q(self):
        return self._sync_queue

    @property
    def async_q(self):
        return self._async_queue

    # Override these methods to implement other queue organizations
    # (e.g. stack or priority queue).
    # These will only be called with appropriate locks held

    def _init(self, maxsize):
        self._queue = deque()

    def _qsize(self):
        return len(self._queue)

    # Put a new item in the queue
    def _put(self, item):
        self._queue.append(item)

    # Get an item from the queue
    def _get(self):
        return self._queue.popleft()

    def _put_internal(self, item):
        self._put(item)
        self._unfinished_tasks += 1
        self._finished.clear()

    def _notify_sync_not_empty(self):
        def f():
            with self._sync_mutex:
                self._sync_not_empty.notify()

        self._loop.run_in_executor(None, f)

    def _notify_sync_not_full(self):
        def f():
            with self._sync_mutex:
                self._sync_not_full.notify()

        fut = self._loop.run_in_executor(None, f)
        fut.add_done_callback(self._pending.discard)
        self._pending.add(fut)

    def _notify_async_not_empty(self, *, threadsafe):
        async def f():
            async with self._async_mutex:
                self._async_not_empty.notify()

        def task_maker():
            task = ensure_future(f(), loop=self._loop)
            task.add_done_callback(self._pending.discard)
            self._pending.add(task)

        if threadsafe:
            self._call_soon_threadsafe(task_maker)
        else:
            self._call_soon(task_maker)

    def _notify_async_not_full(self, *, threadsafe):
        async def f():
            async with self._async_mutex:
                self._async_not_full.notify()

        def task_maker():
            task = ensure_future(f(), loop=self._loop)
            task.add_done_callback(self._pending.discard)
            self._pending.add(task)

        if threadsafe:
            self._call_soon_threadsafe(task_maker)
        else:
            self._call_soon(task_maker)

    def _check_closing(self):
        if self._closing:
            raise RuntimeError('Modification of closed queue is forbidden')


class _SyncQueueProxy:
    '''Create a queue object with a given maximum size.

    If maxsize is <= 0, the queue size is infinite.
    '''

    def __init__(self, parent):
        self._parent = parent

    @property
    def maxsize(self):
        return self._parent._maxsize

    @property
    def closed(self):
        return self._parent.closed

    def task_done(self):
        '''Indicate that a formerly enqueued task is complete.

        Used by Queue consumer threads.  For each get() used to fetch a task,
        a subsequent call to task_done() tells the queue that the processing
        on the task is complete.

        If a join() is currently blocking, it will resume when all items
        have been processed (meaning that a task_done() call was received
        for every item that had been put() into the queue).

        Raises a ValueError if called more times than there were items
        placed in the queue.
        '''
        self._parent._check_closing()
        with self._parent._all_tasks_done:
            unfinished = self._parent._unfinished_tasks - 1
            if unfinished <= 0:
                if unfinished < 0:
                    raise ValueError('task_done() called too many times')
                self._parent._all_tasks_done.notify_all()
                self._parent._loop.call_soon_threadsafe(
                    self._parent._finished.set)
            self._parent._unfinished_tasks = unfinished

    def join(self):
        '''Blocks until all items in the Queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the
        queue. The count goes down whenever a consumer thread calls task_done()
        to indicate the item was retrieved and all work on it is complete.

        When the count of unfinished tasks drops to zero, join() unblocks.
        '''
        with self._parent._all_tasks_done:
            while self._parent._unfinished_tasks:
                self._parent._all_tasks_done.wait()

    def qsize(self):
        '''Return the approximate size of the queue (not reliable!).'''
        return self._parent._qsize()

    @property
    def unfinished_tasks(self):
        '''Return the number of unfinished tasks.'''
        return self._parent._unfinished_tasks

    def empty(self):
        '''Return True if the queue is empty, False otherwise (not reliable!).

        This method is likely to be removed at some point.  Use qsize() == 0
        as a direct substitute, but be aware that either approach risks a race
        condition where a queue can grow before the result of empty() or
        qsize() can be used.

        To create code that needs to wait for all queued tasks to be
        completed, the preferred technique is to use the join() method.
        '''
        return not self._parent._qsize()

    def full(self):
        '''Return True if the queue is full, False otherwise (not reliable!).

        This method is likely to be removed at some point.  Use qsize() >= n
        as a direct substitute, but be aware that either approach risks a race
        condition where a queue can shrink before the result of full() or
        qsize() can be used.
        '''
        return 0 < self._parent._maxsize <= self._parent._qsize()

    def put(self, item, block=True, timeout=None):
        '''Put an item into the queue.

        If optional args 'block' is true and 'timeout' is None (the default),
        block if necessary until a free slot is available. If 'timeout' is
        a non-negative number, it blocks at most 'timeout' seconds and raises
        the Full exception if no free slot was available within that time.
        Otherwise ('block' is false), put an item on the queue if a free slot
        is immediately available, else raise the Full exception ('timeout'
        is ignored in that case).
        '''
        self._parent._check_closing()
        with self._parent._sync_not_full:
            if self._parent._maxsize > 0:
                if not block:
                    if self._parent._qsize() >= self._parent._maxsize:
                        raise SyncQueueFull
                elif timeout is None:
                    while self._parent._qsize() >= self._parent._maxsize:
                        self._parent._sync_not_full.wait()
                elif timeout < 0:
                    raise ValueError("'timeout' must be a non-negative number")
                else:
                    time = self._parent._loop.time
                    endtime = time() + timeout
                    while self._parent._qsize() >= self._parent._maxsize:
                        remaining = endtime - time()
                        if remaining <= 0.0:
                            raise SyncQueueFull
                        self._parent._sync_not_full.wait(remaining)
            self._parent._put_internal(item)
            self._parent._sync_not_empty.notify()
            self._parent._notify_async_not_empty(threadsafe=True)

    def get(self, block=True, timeout=None):
        '''Remove and return an item from the queue.

        If optional args 'block' is true and 'timeout' is None (the default),
        block if necessary until an item is available. If 'timeout' is
        a non-negative number, it blocks at most 'timeout' seconds and raises
        the Empty exception if no item was available within that time.
        Otherwise ('block' is false), return an item if one is immediately
        available, else raise the Empty exception ('timeout' is ignored
        in that case).
        '''
        self._parent._check_closing()
        with self._parent._sync_not_empty:
            if not block:
                if not self._parent._qsize():
                    raise SyncQueueEmpty
            elif timeout is None:
                while not self._parent._qsize():
                    self._parent._sync_not_empty.wait()
            elif timeout < 0:
                raise ValueError("'timeout' must be a non-negative number")
            else:
                time = self._parent._loop.time
                endtime = time() + timeout
                while not self._parent._qsize():
                    remaining = endtime - time()
                    if remaining <= 0.0:
                        raise SyncQueueEmpty
                    self._parent._sync_not_empty.wait(remaining)
            item = self._parent._get()
            self._parent._sync_not_full.notify()
            self._parent._notify_async_not_full(threadsafe=True)
            return item

    def put_nowait(self, item):
        '''Put an item into the queue without blocking.

        Only enqueue the item if a free slot is immediately available.
        Otherwise raise the Full exception.
        '''
        return self.put(item, block=False)

    def get_nowait(self):
        '''Remove and return an item from the queue without blocking.

        Only get an item if one is immediately available. Otherwise
        raise the Empty exception.
        '''
        return self.get(block=False)


class _AsyncQueueProxy:
    '''Create a queue object with a given maximum size.

    If maxsize is <= 0, the queue size is infinite.
    '''

    def __init__(self, parent):
        self._parent = parent

    @property
    def closed(self):
        return self._parent.closed

    def qsize(self):
        """Number of items in the queue."""
        return self._parent._qsize()

    @property
    def unfinished_tasks(self):
        '''Return the number of unfinished tasks.'''
        return self._parent._unfinished_tasks

    @property
    def maxsize(self):
        """Number of items allowed in the queue."""
        return self._parent._maxsize

    def empty(self):
        """Return True if the queue is empty, False otherwise."""
        return self.qsize() == 0

    def full(self):
        """Return True if there are maxsize items in the queue.

        Note: if the Queue was initialized with maxsize=0 (the default),
        then full() is never True.
        """
        if self._parent._maxsize <= 0:
            return False
        else:
            return self.qsize() >= self._parent._maxsize

    async def put(self, item):
        """Put an item into the queue.

        Put an item into the queue. If the queue is full, wait until a free
        slot is available before adding item.

        This method is a coroutine.
        """
        self._parent._check_closing()
        async with self._parent._async_not_full:
            self._parent._sync_mutex.acquire()
            locked = True
            try:
                if self._parent._maxsize > 0:
                    do_wait = True
                    while do_wait:
                        do_wait = (
                            self._parent._qsize() >= self._parent._maxsize
                        )
                        if do_wait:
                            locked = False
                            self._parent._sync_mutex.release()
                            await self._parent._async_not_full.wait()
                            self._parent._sync_mutex.acquire()
                            locked = True

                self._parent._put_internal(item)
                self._parent._async_not_empty.notify()
                self._parent._notify_sync_not_empty()
            finally:
                if locked:
                    self._parent._sync_mutex.release()

    def put_nowait(self, item):
        """Put an item into the queue without blocking.

        If no free slot is immediately available, raise QueueFull.
        """
        self._parent._check_closing()
        with self._parent._sync_mutex:
            if self._parent._maxsize > 0:
                if self._parent._qsize() >= self._parent._maxsize:
                    raise AsyncQueueFull

            self._parent._put_internal(item)
            self._parent._notify_async_not_empty(threadsafe=False)
            self._parent._notify_sync_not_empty()

    async def get(self):
        """Remove and return an item from the queue.

        If queue is empty, wait until an item is available.

        This method is a coroutine.
        """
        self._parent._check_closing()
        async with self._parent._async_not_empty:
            self._parent._sync_mutex.acquire()
            locked = True
            try:
                do_wait = True
                while do_wait:
                    do_wait = self._parent._qsize() == 0

                    if do_wait:
                        locked = False
                        self._parent._sync_mutex.release()
                        await self._parent._async_not_empty.wait()
                        self._parent._sync_mutex.acquire()
                        locked = True

                item = self._parent._get()
                self._parent._async_not_full.notify()
                self._parent._notify_sync_not_full()
                return item
            finally:
                if locked:
                    self._parent._sync_mutex.release()

    def get_nowait(self):
        """Remove and return an item from the queue.

        Return an item if one is immediately available, else raise QueueEmpty.
        """
        self._parent._check_closing()
        with self._parent._sync_mutex:
            if self._parent._qsize() == 0:
                raise AsyncQueueEmpty

            item = self._parent._get()
            self._parent._notify_async_not_full(threadsafe=False)
            self._parent._notify_sync_not_full()
            return item

    def task_done(self):
        """Indicate that a formerly enqueued task is complete.

        Used by queue consumers. For each get() used to fetch a task,
        a subsequent call to task_done() tells the queue that the processing
        on the task is complete.

        If a join() is currently blocking, it will resume when all items have
        been processed (meaning that a task_done() call was received for every
        item that had been put() into the queue).

        Raises ValueError if called more times than there were items placed in
        the queue.
        """
        self._parent._check_closing()
        with self._parent._all_tasks_done:
            if self._parent._unfinished_tasks <= 0:
                raise ValueError('task_done() called too many times')
            self._parent._unfinished_tasks -= 1
            if self._parent._unfinished_tasks == 0:
                self._parent._finished.set()
                self._parent._all_tasks_done.notify_all()

    async def join(self):
        """Block until all items in the queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the
        queue. The count goes down whenever a consumer calls task_done() to
        indicate that the item was retrieved and all work on it is complete.
        When the count of unfinished tasks drops to zero, join() unblocks.
        """
        while True:
            with self._parent._sync_mutex:
                if self._parent._unfinished_tasks == 0:
                    break
            await self._parent._finished.wait()


class PriorityQueue(Queue):
    '''Variant of Queue that retrieves open entries in priority order
    (lowest first).

    Entries are typically tuples of the form:  (priority number, data).

    '''

    def _init(self, maxsize):
        self._queue = []

    def _qsize(self):
        return len(self._queue)

    def _put(self, item):
        heappush(self._queue, item)

    def _get(self):
        return heappop(self._queue)


class LifoQueue(Queue):
    '''Variant of Queue that retrieves most recently added entries first.'''

    def _init(self, maxsize):
        self._queue = deque()

    def _qsize(self):
        return len(self._queue)

    def _put(self, item):
        self._queue.append(item)

    def _get(self):
        return self._queue.pop()
