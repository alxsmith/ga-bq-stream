import webapp2, json, logging, os, time, uuid

from google.cloud import bigquery
from google.appengine.api import memcache, taskqueue
from datetime import date, timedelta

# https://cloud.google.com/bigquery/querying-data#bigquery-sync-query-python
def sync_query(query):
    client = bigquery.Client()
    query_results = client.run_sync_query(query)

    # Use standard SQL syntax for queries.
    # See: https://cloud.google.com/bigquery/sql-reference/
    query_results.use_legacy_sql = False

    query_results.run()

    # Drain the query results by requesting a page at a time.
    page_token = None
    bqdata = []

    while True:
        rows, total_rows, page_token = query_results.fetch_data(
            max_results=10,
            page_token=page_token)

        bqdata.extend(rows)

        for row in rows:
            logging.debug(row)

        if not page_token:
            break

    return bqdata

# queries and turns into JSON
def get_data(q):
	datasetId = os.environ['DATASET_ID']
	tableId   = os.environ['TABLE_ID']

	if len(q) > 0:
		query = q % (datasetId, tableId)
	else:
		query = 'SELECT * FROM %s.%s LIMIT 1000' % (datasetId, tableId)

	bqdata = sync_query(query)

	return json.dumps(bqdata)

## https://cloud.google.com/bigquery/streaming-data-into-bigquery
## function to send data to BQ stream
## https://github.com/GoogleCloudPlatform/python-docs-samples/blob/master/bigquery/cloud-client/stream_data.py
def stream_data(dataset_name, table_name, json_data, time_stamp = time.time()):
    bigquery_client = bigquery.Client()
    dataset = bigquery_client.dataset(dataset_name)
    table = dataset.table(table_name)
    data = json_data

    data['ts'] = time_stamp

    # Reload the table to get the schema.
    table.reload()

    ## get the names of schema
    schema = table.schema
    schema_names = [o.name for o in schema]

    logging.debug('BQ Schema: {}'.format(schema_names))

    # from schema names get list of tuples of the values
    rows = [(data[x] for x in schema_names)]

    # https://googlecloudplatform.github.io/google-cloud-python/stable/bigquery-table.html#google.cloud.bigquery.table.Table.insert_data
    errors = table.insert_data(rows, row_ids = str(uuid.uuid4()))

    if not errors:
    	logging.debug('Loaded 1 row into {}:{}'.format(dataset_name, table_name))
    else:
        logging.error(errors)

class MainHandler(webapp2.RequestHandler):

	## for debugging
	def get(self):
		## allows CORS
		self.response.headers.add_header("Access-Control-Allow-Origin", "*")

		## get example.com?bq=blah
		b = self.request.get("bq")

		## send to async task URL
		task = taskqueue.add(url='/bq-task', params={'bq': b, 'ts': str(time.time())})

	# use in prod
	def post(self):
		## allows CORS
		self.response.headers.add_header("Access-Control-Allow-Origin", "*")

		## get example.com?bq=blah
		b = self.request.get("bq")

		## send to async task URL
		task = taskqueue.add(url='/bq-task', params={'bq': b, 'ts': str(time.time())})

class BqHandler(webapp2.RequestHandler):
	def post(self):

		## get example.com/bq-task?bq=blah
		b = self.request.get("bq")
		ts = self.request.get("ts")

		b = json.loads(b)

		logging.debug('json load: {}'.format(b))

		if len(b) > 0:
			datasetId = os.environ['DATASET_ID']
			tableId   = os.environ['TABLE_ID']

			today = date.today().strftime("%Y%m%d")

			tableId = "%s$%s"%(tableId, today)

			stream_data(datasetId, tableId, b, ts)


class QueryTable(webapp2.RequestHandler):
	def get(self):

		q = self.request.get("q")
		self.response.headers.add_header("Content-Type", "application/json")
		self.response.out.write(get_data(q))

app = webapp2.WSGIApplication([
    ('/bq-streamer', MainHandler),
    ('/bq-task', BqHandler),
    ('/bq-get', QueryTable)
], debug=True)