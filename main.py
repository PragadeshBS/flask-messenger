import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()

hugging_face_url = 'https://api-inference.huggingface.co/models/distilbert-base-uncased-finetuned-sst-2-english'
hugging_face_headers = {
    'Authorization': os.getenv('HUGGING_FACE_API'),
}

data = [{"text": "I love apples"}, {"text": "I hate oranges"}]

r = requests.post(url=hugging_face_url,
                  headers=hugging_face_headers,
                  data=json.dumps(data))
print(r.text)