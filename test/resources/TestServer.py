# -*- coding: utf-8 -*-
from ladon.server.wsgi import LadonWSGIApplication
from werkzeug.wsgi import SharedDataMiddleware
import wsgiref.simple_server
from wsgiref.util import shift_path_info
from os.path import abspath, dirname, join
import os
import sys
import threading
from cherrypy import wsgiserver


THIS_DIR = dirname(abspath(__file__))
service_modules = ['calculator', 'testservice']
port = 8080


class Auth(object):
    """Applies basic authentication where authentication is successful if the user name and the password are the same.

    Taken from http://eddmann.com/posts/creating-a-basic-auth-wsgi-middleware-in-python/
    """
    def __init__(self, app):
        self._app = app

    def __call__(self, environ, start_response):
        if self._authenticated(environ.get('HTTP_AUTHORIZATION')):
            return self._app(environ, start_response)
        return self._login(environ, start_response)

    def _authenticated(self, header):
        from base64 import b64decode
        if not header:
            return False
        _, encoded = header.split(None, 1)
        decoded = b64decode(encoded).decode('UTF-8')
        username, password = decoded.split(':', 1)
        return username == password

    def _login(self, environ, start_response):
        start_response('401 Authentication Required',
                       [('Content-Type', 'text/html'),
                        ('WWW-Authenticate', 'Basic realm="Login"')])
        return [b'Login']


class Director(object):
    """Directs requests a root app or other spps mapped to a single path part above root."""
    def __init__(self, root_app, **other_apps):
        self._root_app = root_app
        self._other_apps = dict([(key.lower(), value) for key, value in other_apps.iteritems()])

    def __call__(self, environ, start_response):
        orig_path = environ.get('PATH_INFO')
        orig_script_name = environ.get('SCRIPT_NAME')
        path_part = (shift_path_info(environ) or '').lower()
        if path_part in self._other_apps:
            return self._other_apps[path_part](environ, start_response)
        else:
            environ['PATH_INFO'] = orig_path
            environ['SCRIPT_NAME'] = orig_script_name
            return self._root_app(environ, start_response)


class Caller(object):
    """Calls the given function in a separate thread."""
    def __init__(self, exit_func):
        self._exit_func = exit_func

    def __call__(self, environ, start_response):
        thread = threading.Thread(target=self._exit_func)
        thread.start()
        start_response('200 OK', [('Content-type', 'text/plain')])
        return "Server shutting down..."


class WebServer(object):

    def shutdown(self):
        raise NotImplementedError

    def serve_forever(self):
        raise NotImplementedError

    def create_wsgi_app(self):
        unsecured = self._create_web_services('Unsecured services')
        unsecured = self._add_shared_data(unsecured)
        secured = self._create_web_services('Secured services')
        secured = self._add_shared_data(secured)
        secured = Auth(secured)
        return Director(unsecured, secure=secured, exit=Caller(self.shutdown))

    def _create_web_services(self, name):
        return LadonWSGIApplication(
            service_modules,
            [join(THIS_DIR, 'services')],
            catalog_name=name,
            catalog_desc='Ladon cannot cover all use cases for Suds, but it is'
                         ' easy to set up and generates WSDLs.')

    def _add_shared_data(self, application):
        """Exposes the files in wsdls folder"""
        mapping = {'/wsdls': os.path.join(os.path.dirname(__file__), 'wsdls')}
        return SharedDataMiddleware(application, mapping)


class CherryPyWebServer(WebServer):
    def __init__(self):
        self.server = None

    def shutdown(self):
        """Shutdown is not immediate. It will finish when all open sockets
        close, e.g. due to timeout when using persistent sockets."""
        self.server.stop()

    def serve_forever(self):
        application = self.create_wsgi_app()
        self.server = wsgiserver.CherryPyWSGIServer(('localhost', port),
                                                    application)
        self.server.start()


class WsgiRefWebServer(WebServer):
    def __init__(self):
        self._shutdown = False

    def shutdown(self):
        self._shutdown = True

    def serve_forever(self):
        application = self.create_wsgi_app()
        server = wsgiref.simple_server.make_server('localhost', port,
                                                   application)
        while not self._shutdown:
            server.handle_request()


def main(*args):
    servers = {
        'CHERRYPY': CherryPyWebServer,
        'WSGIREF': WsgiRefWebServer
    }
    server_type = 'CHERRYPY'
    if args:
        server_type = args[0]
    server_type = server_type.upper().replace(' ', '')
    try:
        server = servers[server_type]()
    except KeyError:
        raise ValueError("%s is not a supported server type" % server_type)
    stuff = [
        ('Unsecured web services', 'http://localhost:%(port)s/'),
        ('Unsecured files', 'http://localhost:%(port)s/wsdls/'),
        ('Secured web services', 'http://localhost:%(port)s/secure/'),
        ('Secured files', 'http://localhost:%(port)s/secure/wsdls/'),
        ('Shutdown the server', 'http://localhost:8080/shutdown')
    ]
    for item in stuff:
        print item[0] + ' : ' + item[1] % {'port': port}
    print "Starting the %s web server" % server_type
    server.serve_forever()


if __name__ == '__main__':
    args = sys.argv[1:]
    main(*args)