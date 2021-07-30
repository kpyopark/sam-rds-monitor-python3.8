import json
import boto3
import base64
import os
import mysql.connector
from mysql.connector import errorcode
from botocore.exceptions import ClientError

region = ""
reuse_count = 0
dbendpoint = ""
dbuser = ""
dbpass = ""
dbname = ""
dbport = 3306
snstopic = ""

def initialize():
    global region
    global reuse_count
    global dbendpoint
    global dbuser
    global dbpass
    global dbname
    global dbport
    global snstopic
    if reuse_count % 10 == 0:
        region = ""
    if region == "":
        region = os.environ.get('AWS_REGION')
        dbsecret = os.environ.get('dbsecret')
        dbcred = get_secret(dbsecret)
        dbuser = dbcred['username']
        dbpass = dbcred['password']
        dbendpoint = dbcred['host']
        dbname = dbcred['dbname']
        dbport = dbcred['port']
        snstopic = os.environ.get('snstopic')
        reuse_count = reuse_count + 1

def get_secret(secret_name):

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region
    )
    # In this sample we only handle the specific exceptions for the 'GetSecretValue' API.
    # See https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
    # We rethrow the exception by default.
    get_secret_value_response = {}
    try:
        print('secret_name:' + secret_name)
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
        print("received value.")
        # print(get_secret_value_response)
    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            # An error occurred on the server side.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            # You provided an invalid value for a parameter.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            # You provided a parameter value that is not valid for the current state of the resource.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            # We can't find the resource that you asked for.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        else:
            print(e)
            raise e
    
    # print(get_secret_value_response)
    return json.loads(get_secret_value_response['SecretString'])

def send_message(subject, message):
    sns = boto3.client(service_name='sns',
        region_name=region)
    print('SNS Topic:' + snstopic)
    sns.publish(TopicArn=snstopic, 
            Message=message, 
            Subject=subject)

def lambda_handler(event, context):
    """Sample pure Lambda function

    Parameters
    ----------
    event: dict, required
        API Gateway Lambda Proxy Input Format

        Event doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format

    context: object, required
        Lambda Context runtime methods and attributes

        Context doc: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
    ------
    API Gateway Lambda Proxy Output Format: dict

        Return doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
    """

    # try:
    #     ip = requests.get("http://checkip.amazonaws.com/")
    # except requests.RequestException as e:
    #     # Send some context about this error to Lambda Logs
    #     print(e)

    #     raise e
    print("initialize")
    initialize()
    print("Connect to the database")
    try:
        cnx = mysql.connector.connect(user=dbuser, password=dbpass,
            host=dbendpoint, database=dbname)
        cursor = cnx.cursor()

        query = """
select trx_id, trx_state, trx_mysql_thread_id, trx_started, secs_after_opening, trx_rows_modified, user, host, db, command, time, state 
  from (
  select a.trx_id, a.trx_mysql_thread_id, a.trx_state, a.trx_started, 
    TIMESTAMPDIFF(second, a.trx_started, now()) as secs_after_opening, 
    a.trx_rows_modified, b.user, b.host, b.db, b.command, b.time, b.state 
  from information_schema.innodb_trx a join information_schema.processlist b 
  on (a.trx_mysql_thread_id = b.id)
  ) inner_a
where secs_after_opening >= 100
 order by trx_started
        """
        print(query)
        cursor.execute(query)
        records = cursor.fetchall()
        print('row count:' + str(cursor.rowcount))
        if cursor.rowcount > 0 :
            message = (
'The following processes has long transactions on database [' + dbname + '] - [' + dbendpoint + ']'
'\n'
            )
            print('len:', len(records))
            for (trx_id, trx_state, trx_mysql_thread_id, trx_started, secs_after_opening, trx_rows_modified, user, host, db, command, time, state) in records:
                line = 'Transaction Id:[' + trx_id + '] Transaction State:[' + trx_state + '] Thread ID:[' + str(trx_mysql_thread_id) + '] Start Time:[' + str(trx_started) + '] Duration(Sec):[' + str(secs_after_opening) + '] Modified Rows:[' + str(trx_rows_modified) + '] User:[' + user + '] State:[' + state + '] \n'
                print(line)
                message = message + line
            subject = "[Critical] Database [" + dbname + "] has long transactions. [count:" + str(cursor.rowcount) + "]"
            send_message(subject, message)
        else :
            print("There is no long transaction.")

    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Something is wrong with your user name or password")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            print("Database does not exist")
        else:
            print(err)
    else:
        cnx.close()
    print("Closing.")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Succeeded.",
        }),
    }
