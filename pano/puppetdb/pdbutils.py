import datetime
import queue
from threading import Thread

from pano.puppetdb import puppetdb


class UTC(datetime.tzinfo):
    """UTC"""

    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return str('UTC')

    def dst(self, dt):
        return datetime.timedelta(0)

    def __repr__(self):
        return str('<UTC>')

    def __str__(self):
        return str('UTC')

    def __unicode__(self):
        return 'UTC'


def json_to_datetime(date):
    """Tranforms a JSON datetime string into a timezone aware datetime
    object with a UTC tzinfo object.

    :param date: The datetime representation.
    :type date: :obj:`string`

    :returns: A timezone aware datetime object.
    :rtype: :class:`datetime.datetime`
    """
    return datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%fZ').replace(
        tzinfo=UTC())


def is_unreported(node_report_timestamp, unreported=2):
    try:
        if node_report_timestamp is None:
            return True
        last_report = json_to_datetime(node_report_timestamp)
        last_report = last_report.replace(tzinfo=None)
        now = datetime.datetime.utcnow()
        unreported_border = now - datetime.timedelta(hours=unreported)
        if last_report < unreported_border:
            return True
    except AttributeError:
        return True
    return False


def run_dashboard_jobs():
    num_threads = 6
    jobs_q = queue.Queue()
    out_q = queue.Queue()

    def db_threaded_requests(i, q):
        while True:
            t_job = q.get()
            t_path = t_job['path']
            t_params = t_job.get('params', {})
            t_verify = t_job.get('verify', False)
            t_api_v = t_job.get('api', 'v3')
            results = puppetdb.api_get(
                path=t_path,
                params=puppetdb.mk_puppetdb_query(t_params),
                api_version=t_api_v,
                verify=t_verify,
            )
            out_q.put({t_job['id']: results})
            q.task_done()

    for i in range(num_threads):
        worker = Thread(target=db_threaded_requests, args=(i, jobs_q))
        worker.setDaemon(True)
        worker.start()

    events_params = {
        'query':
            {
                1: '["=","latest-report?",true]'
            },
        'summarize-by': 'certname',
    }
    nodes_params = {
        'limit': 25,
        'order-by': {
            'order-field': {
                'field': 'report-timestamp',
                'order': 'desc',
            },
            'query-field': {'field': 'name'},
        },
    }

    jobs = {
        'population': {
            'id': 'population',
            'path': '/metrics/mbean/com.puppetlabs.puppetdb.query.population:type=default,name=num-nodes',
            'verify': False,
        },
        'tot_resource': {
            'id': 'tot_resource',
            'path': '/metrics/mbean/com.puppetlabs.puppetdb.query.population:type=default,name=num-resources',
            'verify': False,
        },
        'avg_resource': {
            'id': 'avg_resource',
            'path': '/metrics/mbean/com.puppetlabs.puppetdb.query.population:type=default,name=avg-resources-per-node',
            'verify': False,
        },
        'all_nodes': {
            'id': 'all_nodes',
            'path': '/nodes',
            'verify': False,
        },
        'events': {
            'id': 'event-counts',
            'path': 'event-counts',
            'params': events_params,
            'verify': False,
        },
        'nodes': {
            'id': 'nodes',
            'path': '/nodes',
            'params': nodes_params,
            'verify': False,
        },
    }

    for job in jobs:
        jobs_q.put(jobs[job])
    jobs_q.join()
    job_results = {}
    while True:
        try:
            msg = (out_q.get_nowait())
            job_results = dict(
                list(job_results.items()) + list(msg.items()))
        except queue.Empty:
            break

    return job_results
