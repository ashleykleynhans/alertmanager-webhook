#!/usr/bin/env python3
import requests
import json

PAYLOAD = {
   "status":"resolved",
   "groupLabels":{
      "alertname":"instance_down"
   },
   "commonAnnotations":{
      "description":"i-0d7188fkl90bac100 of job ec2-sp-node_exporter has been down for more than 2 minutes.",
      "summary":"Instance i-0d7188fkl90bac100 down"
   },
   "alerts":[
      {
         "status":"resolved",
         "labels":{
            "name":"olokinho01-prod",
            "instance":"i-0d7188fkl90bac100",
            "job":"ec2-sp-node_exporter",
            "alertname":"instance_down",
            "os":"linux",
            "severity":"page"
         },
         "endsAt":"2022-11-22T16:16:19.376244942-03:00",
         "generatorURL":"http://pmts.io:9090",
         "startsAt":"2022-11-22T16:02:19.376245319-03:00",
         "annotations":{
            "description":"i-0d7188fkl90bac100 of job ec2-sp-node_exporter has been down for more than 2 minutes.",
            "summary":"Instance i-0d7188fkl90bac100 down"
         }
      }
   ],
   "version":"4",
   "receiver":"infra-alert",
   "externalURL":"http://alm.io:9093",
   "commonLabels":{
      "name":"olokinho01-prod",
      "instance":"i-0d7188fkl90bac100",
      "job":"ec2-sp-node_exporter",
      "alertname":"instance_down",
      "os":"linux",
      "severity":"page"
   }
}

r = requests.post('http://127.0.0.1:8090/warning', json=PAYLOAD)
print(json.dumps(r.json(), indent=4, default=str))
