"""Thin FastAPI adapter over the existing IndicPass password-strength engine.

This package contains no password-analysis logic of its own. Every value a
response carries comes from
:class:`indicpass.password.meter.IndicPassMeter` -- built once at process
startup, exactly the way ``scripts/check_password.py`` builds it -- and
serialised with the same :meth:`~indicpass.password.result.PasswordStrengthResult.to_dict`
the CLI's ``--json`` mode already uses. See ``docs/frontend.md`` for the
architecture and ``api/tests/test_api.py`` for the check that this adapter
and a direct call to the meter agree byte for byte on the same password.
"""
