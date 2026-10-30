"""Real cryptographic WebAuthn ceremonies over isolated HTTP; no browser or live credentials."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url as encode, base64url_to_bytes as decode

ROOT = Path(__file__).resolve().parents[1]


class Checks(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='jobfind-passkeys-')
        temp = Path(self.scratch.name)
        cfg = json.loads((ROOT/'config/example.json').read_text())
        cfg['data_dir'] = str(temp/'data')
        cfg['hermes']['output_dir'] = str(temp/'output')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            self.port = sock.getsockname()[1]
        cfg['server']['port'] = self.port
        self.origin = f'http://localhost:{self.port}'
        path = temp/'config.json'
        path.write_text(json.dumps(cfg))
        self.env = dict(os.environ,JOBFIND_CONFIG=str(path))
        self.secret = secrets.token_urlsafe(24)
        self.cfg = cfg
        subprocess.run([sys.executable,str(ROOT/'jobfind.py'),'password'],input=self.secret+'\n',text=True,env=self.env,check=True,capture_output=True)
        self.process = subprocess.Popen([sys.executable,str(ROOT/'jobfind.py'),'start'],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.cookies = {}
        self.csrf = ''
        for _ in range(100):
            try:
                if self.request('GET','/api/health')[0]==200:
                    break
            except OSError:
                time.sleep(.03)
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.identifier = secrets.token_bytes(32)

    def tearDown(self):
        self.process.terminate()
        self.process.wait(timeout=10)
        self.scratch.cleanup()

    def request(self,method,path,payload=None,origin=None,csrf=True,cookies=None):
        headers={'Host':f'localhost:{self.port}','Origin':origin or self.origin}
        jar = self.cookies if cookies is None else cookies
        headers['Cookie']='; '.join(f'{key}={value}' for key,value in jar.items())
        if self.csrf and csrf:
            headers['X-CSRF-Token']=self.csrf
        body=json.dumps(payload) if payload is not None else None
        if payload is not None:
            headers['Content-Type']='application/json'
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        try:
            connection.request(method,path,body,headers)
            response=connection.getresponse()
            raw=response.read()
            for key,value in response.getheaders():
                if key.lower()=='set-cookie':
                    name,content=value.split(';',1)[0].split('=',1)
                    if content: jar[name]=content
                    else: jar.pop(name,None)
            return response.status,json.loads(raw) if raw else {}
        finally:
            connection.close()

    def login(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        connection.request('POST','/login','password='+self.secret,{'Host':f'localhost:{self.port}','Origin':self.origin,'Content-Type':'application/x-www-form-urlencoded'})
        response=connection.getresponse()
        self.assertEqual(response.status,303)
        cookie=response.getheader('Set-Cookie').split(';',1)[0]
        key,value=cookie.split('=',1)
        self.cookies[key]=value
        response.read()
        connection.close()
        self.csrf=self.request('GET','/api/csrf')[1]['token']

    def registration(self,options,origin=None,flags=0x45):
        numbers=self.private.public_key().public_numbers()
        cose=cbor2.dumps({1:2,3:-7,-1:1,-2:numbers.x.to_bytes(32,'big'),-3:numbers.y.to_bytes(32,'big')})
        auth=hashlib.sha256(b'localhost').digest()+bytes([flags])+bytes(4)+bytes(16)+len(self.identifier).to_bytes(2,'big')+self.identifier+cose
        client=json.dumps(dict(type='webauthn.create',challenge=options['challenge'],origin=origin or self.origin,crossOrigin=False)).encode()
        return dict(id=encode(self.identifier),rawId=encode(self.identifier),type='public-key',response=dict(clientDataJSON=encode(client),attestationObject=encode(cbor2.dumps(dict(fmt='none',attStmt={},authData=auth)))))

    def enroll(self):
        self.login()
        status,result=self.request('POST','/api/passkeys/register/options',dict(password=self.secret,name='Fictional authenticator'))
        self.assertEqual(status,200)
        options=result['options']
        self.assertEqual(options['authenticatorSelection']['userVerification'],'required')
        self.assertEqual(options['authenticatorSelection']['residentKey'],'required')
        self.handle=options['user']['id']
        self.assertEqual(self.request('POST','/api/passkeys/register/verify',dict(credential=self.registration(options)))[0],200)
        self.assertEqual(len(self.request('GET','/api/passkeys')[1]['passkeys']),1)

    def assertion(self,options,*,origin=None,flags=5,count=1,rp='localhost',cross=False,handle=None,bad_signature=False):
        client=json.dumps(dict(type='webauthn.get',challenge=options['challenge'],origin=origin or self.origin,crossOrigin=cross)).encode()
        auth=hashlib.sha256(rp.encode()).digest()+bytes([flags])+count.to_bytes(4,'big')
        signature=self.private.sign(auth+hashlib.sha256(client).digest(),ec.ECDSA(hashes.SHA256()))
        if bad_signature:
            signature=signature[:-1]+bytes([signature[-1]^1])
        return dict(id=encode(self.identifier),rawId=encode(self.identifier),type='public-key',response=dict(clientDataJSON=encode(client),authenticatorData=encode(auth),signature=encode(signature),userHandle=handle or self.handle))

    def test_enrollment_and_passwordless_login(self):
        self.enroll()
        self.request('POST','/logout')
        self.csrf=''
        options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
        assertion=self.assertion(options)
        cookie_snapshot=dict(self.cookies)
        self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=assertion))[0],200)
        self.assertEqual(self.request('GET','/api/jobs')[0],200)
        # A consumed browser-bound challenge never creates another session.
        self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=assertion),cookies=cookie_snapshot)[0],400)

    def test_registration_requires_session_csrf_password_and_uv(self):
        self.assertEqual(self.request('POST','/api/passkeys/register/options',dict(password=self.secret))[0],401)
        self.login()
        self.assertEqual(self.request('POST','/api/passkeys/register/options',dict(password=self.secret),csrf=False)[0],403)
        self.assertEqual(self.request('POST','/api/passkeys/register/options',dict(password='wrong'))[0],403)
        options=self.request('POST','/api/passkeys/register/options',dict(password=self.secret))[1]['options']
        self.assertEqual(self.request('POST','/api/passkeys/register/verify',dict(credential=self.registration(options,flags=0x41)))[0],400)
        self.assertEqual(self.request('GET','/api/passkeys')[1]['passkeys'],[])

    def test_reject_forgery_origin_rp_uv_and_user_handle(self):
        self.enroll()
        self.request('POST','/logout')
        self.csrf=''
        for changes in ({'bad_signature':True},{'origin':'https://evil.example'},{'rp':'evil.example'},{'flags':1}):
            options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
            self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options,**changes)))[0],400)
            self.assertEqual(self.request('GET','/api/jobs')[0],401)
        # Failure throttling is shared with password login.
        options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
        self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options,handle=encode(b'other owner'))))[0],400)
        self.assertEqual(self.request('POST','/api/passkeys/auth/options',{})[0],429)

    def test_challenge_browser_binding_expiry_cross_origin_and_removal(self):
        self.enroll()
        self.assertEqual(self.request('POST','/api/passkeys/auth/options',{},origin='https://evil.example')[0],403)
        options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
        self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options)),cookies={})[0],400)
        options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
        self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options,cross=True)))[0],400)
        options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
        import sqlite3
        with sqlite3.connect(Path(self.cfg['data_dir'])/'auth.sqlite3') as db:
            db.execute('UPDATE passkey_challenges SET expires_at=0')
        db.close()
        self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options)))[0],400)
        identifier=self.request('GET','/api/passkeys')[1]['passkeys'][0]['id']
        self.assertEqual(self.request('POST','/api/passkeys/delete',dict(id=identifier,password=self.secret))[0],200)
        self.assertEqual(self.request('GET','/api/passkeys')[1]['passkeys'],[])
        self.assertEqual(self.request('POST','/api/passkeys/auth/options',{})[0],400)

    def test_password_reset_revokes_keys_and_sessions(self):
        self.enroll()
        subprocess.run([sys.executable,str(ROOT/'jobfind.py'),'password'],input=self.secret+'\n',text=True,env=self.env,check=True,capture_output=True)
        self.assertEqual(self.request('GET','/api/jobs')[0],401)
        self.assertEqual(self.request('POST','/api/passkeys/auth/options',{})[0],400)

    def test_counter_replay_and_synced_zero_counter(self):
        self.enroll()
        for _ in range(2):
            options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
            self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options,count=0)))[0],200)
        for count,expected in ((1,200),(1,400),(2,200)):
            options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
            self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options,count=count)))[0],expected)

    def test_registration_bound_to_original_session(self):
        self.login()
        options=self.request('POST','/api/passkeys/register/options',dict(password=self.secret))[1]['options']
        self.login()  # Same browser, but a different session must not inherit password proof.
        self.assertEqual(self.request('POST','/api/passkeys/register/verify',dict(credential=self.registration(options)))[0],400)
        self.assertEqual(self.request('GET','/api/passkeys')[1]['passkeys'],[])

    def test_removal_revokes_passkey_sessions_and_refreshes_csrf(self):
        self.enroll()
        password_browser = dict(self.cookies)
        options=self.request('POST','/api/passkeys/auth/options',{})[1]['options']
        self.assertEqual(self.request('POST','/api/passkeys/auth/verify',dict(credential=self.assertion(options)))[0],200)
        passkey_browser = dict(self.cookies)
        self.cookies = password_browser
        identifier=self.request('GET','/api/passkeys')[1]['passkeys'][0]['id']
        status,result=self.request('POST','/api/passkeys/delete',dict(id=identifier,password=self.secret))
        self.assertEqual(status,200)
        self.assertEqual(self.request('GET','/api/jobs',cookies=passkey_browser)[0],401)
        self.csrf=result['csrf']
        self.assertEqual(self.request('GET','/api/csrf')[1]['token'],self.csrf)
        self.assertEqual(self.request('POST','/logout')[0],303)


if __name__=='__main__':
    unittest.main(verbosity=2)
