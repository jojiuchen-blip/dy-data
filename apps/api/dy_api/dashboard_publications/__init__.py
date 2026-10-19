"""Immutable, permission-neutral analytical publications.

Import domain builders explicitly during migration/worker startup. Reading a
publication never initializes tables or imports a business calculator.
"""
