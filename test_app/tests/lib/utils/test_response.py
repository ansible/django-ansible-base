#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import csv
from io import StringIO

from ansible_base.lib.utils.response import CSVStreamResponse


def test_csv_stream_response():
    expected = [b'header,other\r\n', b'data0,other0\r\n', b'data1,other1\r\n', b'data2,other2\r\n', b'data3,other3\r\n', b'data4,other4\r\n']

    def data_generator():
        yield ["header", "other"]
        for i in range(5):
            yield [f"data{i}", f"other{i}"]

    stream = CSVStreamResponse(data_generator(), filename="manifest.csv").stream()
    response = list(stream.streaming_content)
    assert response == expected

    csv_file = StringIO("".join(item.decode() for item in response))
    for ix, row in enumerate(csv.DictReader(csv_file)):
        assert row == {"header": f"data{ix}", "other": f"other{ix}"}
