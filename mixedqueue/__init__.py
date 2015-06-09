import asyncio

from heapq import heappush, heappop
import threading

from collections import deque
from queue import Empty as SyncQueueEmpty, Full as SyncQueueFull
from asyncio import (QueueEmpty as AsyncQueueEmpty, QueueFull as
                     AsyncQueueFull)
from time import monotonic

__version__ = '0.0.1'


class Queue:
    def __init__(self, maxsize=0, *, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self._loop = loop
        self._maxsize = maxsize

        self._init(maxsize)

        self._unfinished_tasks = 0

        self._mutex = threading.Lock()
        self._not_empty = threading.Condition(self._mutex)
        self._not_full = threading.Condition(self._mutex)
        self._all_tasks_done = threading.Condition(self._mutex)

        # Futures.
        self._getters = deque()
        # Pairs of (item, Future).
        self._putters = deque()
        self._finished = asyncio.Event(loop=self._loop)
        self._finished.set()

        self._sync_queue = SyncQueue(self)
        self._async_queue = AsyncQueue(self)

    @property
    def maxsize(self):
        return self._maxsize

    @property
    def sync_queue(self):
        return self._sync_queue

    @property
    def async_queue(self):
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

    def _consume_done_getters(self):
        # Delete waiters at the head of the get() queue who've timed out.
        while self._getters and self._getters[0].done():
            self._getters.popleft()

    def _consume_done_putters(self):
        # Delete waiters at the head of the put() queue who've timed out.
        while self._putters and self._putters[0][1].done():
            self._putters.popleft()


class SyncQueue:
    '''Create a queue object with a given maximum size.

    If maxsize is <= 0, the queue size is infinite.
    '''

    def __init__(self, parent):
        self._parent = parent

    @property
    def maxsize(self):
        return self._parent._maxsize

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
        with self._parent._all_tasks_done:
            unfinished = self._parent._unfinished_tasks - 1
            if unfinished <= 0:
                if unfinished < 0:
                    raise ValueError('task_done() called too many times')
                self._parent._all_tasks_done.notify_all()
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
        with self._parent._not_full:
            if self._parent._maxsize > 0:
                if not block:
                    if self._parent._qsize() >= self._parent._maxsize:
                        raise SyncQueueFull
                elif timeout is None:
                    while self._parent._qsize() >= self._parent._maxsize:
                        self._parent._not_full.wait()
                elif timeout < 0:
                    raise ValueError("'timeout' must be a non-negative number")
                else:
                    endtime = monotonic() + timeout
                    while self._parent._qsize() >= self._parent._maxsize:
                        remaining = endtime - monotonic()
                        if remaining <= 0.0:
                            raise SyncQueueFull
                        self._parent._not_full.wait(remaining)
            self._parent._put(item)
            self._parent._unfinished_tasks += 1
            self._parent._not_empty.notify()

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
        with self._parent._not_empty:
            if not block:
                if not self._parent._qsize():
                    raise SyncQueueEmpty
            elif timeout is None:
                while not self._parent._qsize():
                    self._parent._not_empty.wait()
            elif timeout < 0:
                raise ValueError("'timeout' must be a non-negative number")
            else:
                endtime = monotonic() + timeout
                while not self._parent._qsize():
                    remaining = endtime - monotonic()
                    if remaining <= 0.0:
                        raise SyncQueueEmpty
                    self._parent._not_empty.wait(remaining)
            item = self._parent._get()
            self._parent._not_full.notify()
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


class AsyncQueue:
    '''Create a queue object with a given maximum size.

    If maxsize is <= 0, the queue size is infinite.
    '''

    def __init__(self, parent):
        self._parent = parent

    def __put_internal(self, item):
        self._parent._put(item)
        self._parent._unfinished_tasks += 1
        self._parent._finished.clear()

    def qsize(self):
        """Number of items in the queue."""
        return self._parent._qsize()

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

    @asyncio.coroutine
    def put(self, item):
        """Put an item into the queue.

        Put an item into the queue. If the queue is full, wait until a free
        slot is available before adding item.

        This method is a coroutine.
        """
        self._parent._consume_done_getters()
        if self._parent._getters:
            assert not self._parent._queue, (
                'queue non-empty, why are getters waiting?'
            )

            getter = self._parent._getters.popleft()
            self._parent.__put_internal(item)

            # getter cannot be cancelled, we just removed done getters
            getter.set_result(self._parent._get())

        elif (self._parent._maxsize > 0 and
              self._parent._maxsize <= self.qsize()):
            waiter = asyncio.Future(loop=self._parent._loop)

            self._parent._putters.append((item, waiter))
            yield from waiter

        else:
            self.__put_internal(item)

    def put_nowait(self, item):
        """Put an item into the queue without blocking.

        If no free slot is immediately available, raise QueueFull.
        """
        self._parent._consume_done_getters()
        if self._parent._getters:
            assert self.empty(), ('queue non-empty, why are getters waiting?')

            getter = self._parent._getters.popleft()
            self.__put_internal(item)

            # getter cannot be cancelled, we just removed done getters
            getter.set_result(self._parent._get())

        elif (self._parent._maxsize > 0 and
              self._parent._maxsize <= self.qsize()):
            raise AsyncQueueFull
        else:
            self.__put_internal(item)

    @asyncio.coroutine
    def get(self):
        """Remove and return an item from the queue.

        If queue is empty, wait until an item is available.

        This method is a coroutine.
        """
        self._parent._consume_done_putters()
        if self._parent._putters:
            assert self.full(), 'queue not full, why are putters waiting?'
            item, putter = self._parent._putters.popleft()
            self.__put_internal(item)

            # When a getter runs and frees up a slot so this putter can
            # run, we need to defer the put for a tick to ensure that
            # getters and putters alternate perfectly. See
            # ChannelTest.test_wait.
            self._parent._loop.call_soon(putter._set_result_unless_cancelled,
                                         None)

            return self._parent._get()

        elif self.qsize():
            return self._parent._get()
        else:
            waiter = asyncio.Future(loop=self._parent._loop)

            self._parent._getters.append(waiter)
            return (yield from waiter)

    def get_nowait(self):
        """Remove and return an item from the queue.

        Return an item if one is immediately available, else raise QueueEmpty.
        """
        self._parent._consume_done_putters()
        if self._parent._putters:
            assert self.full(), 'queue not full, why are putters waiting?'
            item, putter = self._parent._putters.popleft()
            self.__put_internal(item)
            # Wake putter on next tick.

            # getter cannot be cancelled, we just removed done putters
            putter.set_result(None)

            return self._parent._get()

        elif self.qsize():
            return self._parent._get()
        else:
            raise AsyncQueueEmpty

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
        if self._parent._unfinished_tasks <= 0:
            raise ValueError('task_done() called too many times')
        self._parent._unfinished_tasks -= 1
        if self._parent._unfinished_tasks == 0:
            self._parent._finished.set()

    @asyncio.coroutine
    def join(self):
        """Block until all items in the queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the
        queue. The count goes down whenever a consumer calls task_done() to
        indicate that the item was retrieved and all work on it is complete.
        When the count of unfinished tasks drops to zero, join() unblocks.
        """
        if self._parent._unfinished_tasks > 0:
            yield from self._parent._finished.wait()


class PriorityQueue(SyncQueue):
    '''Variant of Queue that retrieves open entries in priority order
    (lowest first).

    Entries are typically tuples of the form:  (priority number, data).

    '''

    def _init(self, maxsize):
        self.queue = []

    def _qsize(self):
        return len(self.queue)

    def _put(self, item):
        heappush(self.queue, item)

    def _get(self):
        return heappop(self.queue)


class LifoQueue(SyncQueue):
    '''Variant of Queue that retrieves most recently added entries first.'''

    def _init(self, maxsize):
        self.queue = []

    def _qsize(self):
        return len(self.queue)

    def _put(self, item):
        self.queue.append(item)

    def _get(self):
        return self.queue.pop()
