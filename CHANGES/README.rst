.. _Adding change notes with your PRs:

Adding change notes with your PRs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is very important to maintain a log for news of how
updating to the new version of the software will affect
end-users. This is why we enforce collection of the change
fragment files in pull requests as per `Towncrier philosophy`_.

The idea is that when somebody makes a change, they must record
the bits that would affect end-users only including information
that would be useful to them. Then, when the maintainers publish
a new release, they'll automatically use these records to compose
a change log for the respective version.

How to name a change log entry file
-----------------------------------

Fragments live in the ``CHANGES/`` directory and are named
``{issue_or_pr_number}.{type}``, where ``type`` is one of:

* ``feature``: A new behavior, public APIs. That sort of stuff.
* ``bugfix``: A bug fix for something we deemed an improper undesired
  behavior that got corrected in the release to match pre-agreed
  expectations.
* ``doc``: A change to the documentation.
* ``removal``: A deprecation or removal of public API.
* ``misc``: A small internal change not visible to end-users.

For example, ``123.feature`` or ``456.bugfix``. Write the content in
reStructuredText, in the past tense, as a full sentence.

To preview the upcoming changelog, run::

    $ towncrier build --draft

.. _Towncrier philosophy:
   https://towncrier.readthedocs.io/en/stable/#philosophy
