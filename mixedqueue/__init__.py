import asyncio

import threading


from collections import deque
from queue import Empty as SyncQueueEmpty, Full as SyncQueueFull
from time import monotonic


__version__ = '0.0.1'


class Queue:

    def __init__(self, maxsize=0, *, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self._loop = loop
        self._maxsize = maxsize

        self._init(maxsize)

        self._sync_mutex = threading.Lock()
        self._async_mutex = asyncio.Lock(loop=loop)
        self._sync_not_empty = threading.Condition(self._sync_mutex)
        self._async_not_empty = asyncio.Condition(self._async_mutex, loop=loop)
        self._sync_not_full = threading.Condition(self._sync_mutex)
        self._async_not_full = asyncio.Condition(self._async_mutex, loop=loop)
        self._sync_all_tasks_done = threading.Condition(self._sync_mutex)
        self._async_all_tasks_done = asyncio.Condition(self._async_mutex,
                                                         loop=loop)

        self._sync_queue = SyncQueue(self)
        self._async_queue = AsyncQueue(self, loop=loop)



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


class SyncQueue:

    '''Create a queue object with a given maximum size.

    If maxsize is <= 0, the queue size is infinite.
    '''

    def __init__(self, parent):
        self._maxsize = parent._maxsize

        self._sync_mutex = parent._sync_mutex
        self._sync_not_empty = parent._sync_not_empty
        self._sync_not_full = parent._sync_not_full
        self._sync_all_tasks_done = parent._sync_all_tasks_done
        self._unfinished_tasks = 0
        self._qsize = parent._qsize
        self._put = parent._put
        self._get = parent._get

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
        with self._sync_all_tasks_done:
            unfinished = self._unfinished_tasks - 1
            if unfinished <= 0:
                if unfinished < 0:
                    raise ValueError('task_done() called too many times')
                self._sync_all_tasks_done.notify_all()
            self._unfinished_tasks = unfinished

    def join(self):
        '''Blocks until all items in the Queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the
        queue. The count goes down whenever a consumer thread calls task_done()
        to indicate the item was retrieved and all work on it is complete.

        When the count of unfinished tasks drops to zero, join() unblocks.
        '''
        with self._sync_all_tasks_done:
            while self._unfinished_tasks:
                self._sync_all_tasks_done.wait()

    def qsize(self):
        '''Return the approximate size of the queue (not reliable!).'''
        with self._sync_mutex:
            return self._qsize()

    def empty(self):
        '''Return True if the queue is empty, False otherwise (not reliable!).

        This method is likely to be removed at some point.  Use qsize() == 0
        as a direct substitute, but be aware that either approach risks a race
        condition where a queue can grow before the result of empty() or
        qsize() can be used.

        To create code that needs to wait for all queued tasks to be
        completed, the preferred technique is to use the join() method.
        '''
        with self._sync_mutex:
            return not self._qsize()

    def full(self):
        '''Return True if the queue is full, False otherwise (not reliable!).

        This method is likely to be removed at some point.  Use qsize() >= n
        as a direct substitute, but be aware that either approach risks a race
        condition where a queue can shrink before the result of full() or
        qsize() can be used.
        '''
        with self._sync_mutex:
            return 0 < self._maxsize <= self._qsize()

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
        with self._sync_not_full:
            if self._maxsize > 0:
                if not block:
                    if self._qsize() >= self._maxsize:
                        raise SyncQueueFull
                elif timeout is None:
                    while self._qsize() >= self._maxsize:
                        self._sync_not_full.wait()
                elif timeout < 0:
                    raise ValueError("'timeout' must be a non-negative number")
                else:
                    endtime = monotonic() + timeout
                    while self._qsize() >= self._maxsize:
                        remaining = endtime - monotonic()
                        if remaining <= 0.0:
                            raise SyncQueueFull
                        self._sync_not_full.wait(remaining)
            self._put(item)
            self._unfinished_tasks += 1
            self._sync_not_empty.notify()

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
        with self._sync_not_empty:
            if not block:
                if not self._qsize():
                    raise SyncQueueEmpty
            elif timeout is None:
                while not self._qsize():
                    self._sync_not_empty.wait()
            elif timeout < 0:
                raise ValueError("'timeout' must be a non-negative number")
            else:
                endtime = monotonic() + timeout
                while not self._qsize():
                    remaining = endtime - monotonic()
                    if remaining <= 0.0:
                        raise SyncQueueEmpty
                    self._sync_not_empty.wait(remaining)
            item = self._get()
            self._sync_not_full.notify()
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

    def __init__(self, parent, loop):
        self._maxsize = parent._maxsize
        self._loop = loop

        self._async_mutex = parent._async_mutex
        self._sync_mutex = parent._sync_mutex
        self._async_not_empty = parent._async_not_empty
        self._async_not_full = parent._async_not_full
        self._async_all_tasks_done = parent._async_all_tasks_done
        self._unfinished_tasks = 0

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
        with (yield from self._all_tasks_done):
            unfinished = self._unfinished_tasks - 1
            if unfinished <= 0:
                if unfinished < 0:
                    raise ValueError('task_done() called too many times')
                self._all_tasks_done.notify_all()
            self._unfinished_tasks = unfinished

    @asyncio.coroutine
    def join(self):
        '''Blocks until all items in the Queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the
        queue. The count goes down whenever a consumer thread calls task_done()
        to indicate the item was retrieved and all work on it is complete.

        When the count of unfinished tasks drops to zero, join() unblocks.
        '''
        with (yield from self._all_tasks_done):
            while self._unfinished_tasks:
                self._all_tasks_done.wait()

    def qsize(self):
        '''Return the approximate size of the queue (not reliable!).'''
        with self._sync_mutex:
            return self._qsize()

    def empty(self):
        '''Return True if the queue is empty, False otherwise (not reliable!).

        This method is likely to be removed at some point.  Use qsize() == 0
        as a direct substitute, but be aware that either approach risks a race
        condition where a queue can grow before the result of empty() or
        qsize() can be used.

        To create code that needs to wait for all queued tasks to be
        completed, the preferred technique is to use the join() method.
        '''
        with self._sync_mutex:
            return not self._qsize()

    def full(self):
        '''Return True if the queue is full, False otherwise (not reliable!).

        This method is likely to be removed at some point.  Use qsize() >= n
        as a direct substitute, but be aware that either approach risks a race
        condition where a queue can shrink before the result of full() or
        qsize() can be used.
        '''
        with self._sync_mutex:
            return 0 < self._maxsize <= self._qsize()

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
        with self._not_full:
            if self._maxsize > 0:
                if not block:
                    if self._qsize() >= self._maxsize:
                        raise SyncQueueFull
                elif timeout is None:
                    while self._qsize() >= self._maxsize:
                        self._not_full.wait()
                elif timeout < 0:
                    raise ValueError("'timeout' must be a non-negative number")
                else:
                    endtime = monotonic() + timeout
                    while self._qsize() >= self._maxsize:
                        remaining = endtime - monotonic()
                        if remaining <= 0.0:
                            raise SyncQueueFull
                        self._not_full.wait(remaining)
            self._put(item)
            self._unfinished_tasks += 1
            self._not_empty.notify()

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
        with self._not_empty:
            if not block:
                if not self._qsize():
                    raise SyncQueueEmpty
            elif timeout is None:
                while not self._qsize():
                    self.not_empty.wait()
            elif timeout < 0:
                raise ValueError("'timeout' must be a non-negative number")
            else:
                endtime = monotonic() + timeout
                while not self._qsize():
                    remaining = endtime - monotonic()
                    if remaining <= 0.0:
                        raise SyncQueueEmpty
                    self._not_empty.wait(remaining)
            item = self._get()
            self._not_full.notify()
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

    # Override these methods to implement other queue organizations
    # (e.g. stack or priority queue).
    # These will only be called with appropriate locks held

    # Initialize the queue representation
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


class PriorityQueue(SyncQueue):
    '''Variant of Queue that retrieves open entries in priority order (lowest first).

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
