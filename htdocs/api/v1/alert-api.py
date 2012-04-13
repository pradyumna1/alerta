#!/usr/bin/env python
########################################
#
# alerta-api.py - Alerter New Alert API
#
########################################

import os
import sys
try:
    import json
except ImportError:
    import simplejson as json
import stomp
import time
import datetime
import logging
import uuid
import re

__version__ = '1.3'

BROKER_LIST  = [('localhost', 61613)] # list of brokers for failover
ALERT_QUEUE  = '/queue/alerts'
EXPIRATION_TIME = 600 # seconds = 10 minutes

LOGFILE = '/var/log/alerta/alert-api.log'

VALID_SEVERITY    = [ 'CRITICAL', 'MAJOR', 'MINOR', 'WARNING', 'NORMAL', 'INFORM', 'DEBUG' ]
VALID_ENVIRONMENT = [ 'PROD', 'REL', 'QA', 'TEST', 'CODE', 'STAGE', 'DEV', 'LWP','INFRA' ]
VALID_SERVICES    = [ 'R1', 'R2', 'Discussion', 'Soulmates', 'ContentAPI', 'MicroApp', 'FlexibleContent', 'Mutualisation', 'SharedSvcs' ]

SEVERITY_CODE = {
    # ITU RFC5674 -> Syslog RFC5424
    'CRITICAL':       1, # Alert
    'MAJOR':          2, # Crtical
    'MINOR':          3, # Error
    'WARNING':        4, # Warning
    'NORMAL':         5, # Notice
    'INFORM':         6, # Informational
    'DEBUG':          7, # Debug
}

# Extend JSON Encoder to support ISO 8601 format dates
class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()+'Z'
        else:
            return json.JSONEncoder.default(self, obj)

def main():

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s alert-api[%(process)d] %(levelname)s - %(message)s", filename=LOGFILE)

    for e in os.environ:
       logging.debug('%s: %s', e, os.environ[e])

    alert = dict()
    callback = None

    # cgiform = cgi.FieldStorage()
    data = sys.stdin.read()
    logging.info('POST data: %s', data)

    start = time.time()
    status = dict()
    status['response'] = dict()
    status['response']['status'] = 'error'

    if os.environ['REQUEST_URI'].startswith('/alerta/api/v1/alerts/alert.json') and os.environ['REQUEST_METHOD'] == 'POST':

        try:
            alert = json.loads(data)
        except ValueError, e:
            status['response']['status'] = 'error'
            status['response']['message'] = 'could not decode json'
            logging.error('Could not decode JSON - %s', e)
        else:
            # Set any defaults
            if 'severity' not in alert:
                alert['severity'] = 'normal'
            if 'group' not in alert:
                alert['group'] = 'Misc'

            # Check for mandatory attributes
            if 'resource' not in alert:
                status['response']['status'] = 'error'
                status['response']['message'] = 'must supply a resource'
            elif 'event' not in alert:
                status['response']['status'] = 'error'
                status['response']['message'] = 'must supply event name'
            elif 'value' not in alert:
                status['response']['status'] = 'error'
                status['response']['message'] = 'must supply event value'
            elif alert['severity'].upper() not in VALID_SEVERITY:
                status['response']['status'] = 'error'
                status['response']['message'] = 'severity must be one of %s' % ', '.join(VALID_SEVERITY)
            elif 'environment' not in alert or alert['environment'] not in VALID_ENVIRONMENT:
                status['response']['status'] = 'error'
                status['response']['message'] = 'environment must be one of %s' % ', '.join(VALID_ENVIRONMENT)
            elif 'service' not in alert or alert['service'] not in VALID_SERVICES:
                status['response']['status'] = 'error'
                status['response']['message'] = 'service must be one of %s' % ', '.join(VALID_SERVICES)
            elif 'text' not in alert:
                status['response']['status'] = 'error'
                status['response']['message'] = 'must supply alert text'
            else:
                # REQUEST_URI: /alerta/api/v1/alerts/alert.json

                alertid = str(uuid.uuid4()) # random UUID

                headers = dict()
                headers['type']           = "exceptionAlert"
                headers['correlation-id'] = alertid
                headers['persistent']     = 'true'
                headers['expires']        = int(time.time() * 1000) + EXPIRATION_TIME * 1000

                alert['id']            = alertid
                alert['summary']       = '%s - %s %s is %s on %s %s' % (alert['environment'], alert['severity'].upper(), alert['event'], alert['value'], alert['service'], alert['resource'])
                alert['resource']      = (alert['environment'] + '.' + alert['service'] + '.' + alert['resource']).lower()
                alert['severity']      = alert['severity'].upper()
                alert['severityCode']  = SEVERITY_CODE[alert['severity']]
                alert['environment']   = alert['environment'].upper()
                alert['type']          = 'exceptionAlert'
                alert['createTime']    = datetime.datetime.utcnow().isoformat()+'Z'
                alert['origin']        = 'alert-api/%s' % os.uname()[1]

                logging.info('%s : %s', alertid, json.dumps(alert))

                try:
                    conn = stomp.Connection(BROKER_LIST)
                    conn.start()
                    conn.connect(wait=True)
                except Exception, e:
                    print >>sys.stderr, "ERROR: Could not connect to broker - %s" % e
                    logging.error('Could not connect to broker %s', e)
                try:
                    conn.send(json.dumps(alert), headers, destination=ALERT_QUEUE)
                except Exception, e:
                    print >>sys.stderr, "ERROR: Failed to send alert to broker - %s " % e
                    logging.error('Failed to send alert to broker %s', e)
                broker = conn.get_host_and_port()
                logging.info('%s : Alert sent to %s:%s', alertid, broker[0], str(broker[1]))
                conn.disconnect()

                status['response']['id'] = alertid
                status['response']['status'] = 'ok'

    diff = time.time() - start
    status['response']['time'] = "%.3f" % diff
    status['response']['localTime'] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    content = json.dumps(status, cls=DateEncoder)
    if callback is not None:
        content = '%s(%s);' % (callback, content)

    logging.debug('API >>> %s', content)

    print "Content-Type: application/javascript; charset=utf-8"
    print "Content-Length: %s" % len(content)
    print "Expires: -1"
    print "Cache-Control: no-cache"
    print "Pragma: no-cache"
    print ""
    print content

if __name__ == '__main__':
    main()
