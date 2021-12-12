# RSSdiff+

Based on @j-e-d's code for the twitter bot [@nyt_diff](https://twitter.com/nyt_diff) and @xuv's twitter bot [@lesoir_diff](https://twitter.com/lesoir_diff).
Modified for deploying to AWS (DynamoDB for the DB, Lambda/Cloudwatch for execution)

Installation
------------
+ `pip3 install -r requirements.txt`
+ download [wkhtmltopdf](https://wkhtmltopdf.org/downloads.html) and add the binary to your path

Running it locally
------------
+ Set up DynamoDB. Create two tables: rss_ids (partition id: article_id) and
  rss_versions (partition key: article_id, sort_key: version)
+ Set up config.txt. You will need [Twitter keys](https://dev.twitter.com/) and an AWS key pair that has access to the tables created above.
+ Run `./run_diff.sh`

Deploying to AWS
------------
+ Create a new lambda function in AWS lambda. Make sure the lambda function has
  permissions to access the dynamoDB tables you created
+ Set the env variables in the lambda function (same as config.txt)
+ Add Pillow to your lambda function as a layer. You can find the arn
  [here](https://github.com/keithrozario/Klayers/tree/master/deployments/python3.8/arns)
+ Add wkhtmltoimage as a layer. You can find instructions from the wkhtml
  downloads page
+ Package the python code for the lambda. run `pip3 install -r requirements.txt
  --target ...`. Since we are installing Pillow via the lambda layer, remove the
pillow directories. Copy the rssdiff.py file into the same directory, and copy
the img/ fonts/ and css/ folders into a style folder, and move that into the
same directory. Compress, and upload to lambda
+ Set up a cloudwatch event to trigger the lambda function

Credits
-------
+ Original script and idea: @j-e-d Juan E.D. http://unahormiga.com/
+ RSS fetching: @xuv Julien Deswaef http://xuv.be
+ General refactor and support for LATimes, dynamoDB, imgkit: @jstnchng https://twitter.com/jstnchng3
+ Font: [Merriweather](https://fonts.google.com/specimen/Merriweather)
+ Background pattern: [Paper Fibers](http://subtlepatterns.com/paper-fibers/).
