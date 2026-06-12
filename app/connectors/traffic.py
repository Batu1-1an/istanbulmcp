from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import httpx


class TrafficClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1",
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def index_history(self, period: str = "5M") -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/TrafficIndexHistory/1/{period}")
            response.raise_for_status()
            text = response.text.strip()
            if text.startswith("["):
                return json.loads(text)
            return self._parse_xml_history(text)

    def _parse_xml_history(self, text: str) -> list[dict]:
        root = ET.fromstring(text)
        records = []
        for item in root.iter():
            children = list(item)
            if not children:
                continue
            record = {child.tag.split("}")[-1]: child.text for child in children}
            if "TrafficIndex" in record:
                records.append(record)
        return records
