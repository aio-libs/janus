Changes
=======

0.5.0 (2020-04-23)
------------------

- Remove explicit loop arguments and forbid creating queues outside event loops #246

0.4.0 (2018-07-28)
------------------

- Add ``py.typed`` macro #89

- Drop python 3.4 support and fix minimal version python3.5.3 #88

- Add property with that indicates if queue is closed #86

0.3.2 (2018-07-06)
------------------

- Fixed python 3.7 support #97

0.3.1 (2018-01-30)
------------------

- Fixed bug with join() in case tasks are added by sync_q.put() #75

0.3.0 (2017-02-21)
------------------

- Expose `unfinished_tasks` property #34

0.2.4 (2016-12-05)
------------------

- Restore tarball deploying

0.2.3 (2016-07-12)
------------------

- Fix exception type

0.2.2 (2016-07-11)
------------------

- Update asyncio.async() to use asyncio.ensure_future() #6

0.2.1 (2016-03-24)
------------------

- Fix `python setup.py test` command #4

0.2.0 (2015-09-20)
------------------

- Support Python 3.5

0.1.5 (2015-07-24)
------------------

- Use loop.time() instead of time.monotonic()

0.1.1 (2015-06-12)
------------------

- Fix some typos in README and setup.py

- Add addtional checks for loop closing

- Mention DataRobot

0.1.0 (2015-06-11)
------------------

- Initial release
