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
