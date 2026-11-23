"""Compatibility access to the Trae credential decoder."""
if __name__ == '__main__':
    import runpy
    runpy.run_module('buddy_agent_auth.providers.trae.credential_decrypt', run_name='__main__')
else:
    import sys
    from buddy_agent_auth.providers.trae import credential_decrypt as _module
    sys.modules[__name__] = _module
