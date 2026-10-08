#!/usr/bin/env python3
"""One restricted stdin/stdout operation; invoked through authenticated SSH."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from robodojo_collab.transport import mailbox_operation
try:
    p=json.load(sys.stdin)
    result=mailbox_operation(p['root'],p['op'],p['run_id'],p.get('value'))
    print(json.dumps({'result':result}))
except Exception as error:
    print(json.dumps({'error':str(error)}))
