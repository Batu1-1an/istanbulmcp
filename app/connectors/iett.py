from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import iett_rate_limiter


class IettSoapError(RuntimeError):
    pass


class IettClient:
    def __init__(
        self,
        *,
        ulasim_url: str = "https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx",
        ibb_url: str = "https://api.ibb.gov.tr/iett/ibb/ibb.asmx",
        timeout: float = 20.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.ulasim_url = ulasim_url
        self.ibb_url = ibb_url
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or iett_rate_limiter()

    async def line_info(self, line_code: str) -> list[dict[str, Any]]:
        text = await self._soap_call(
            self.ulasim_url,
            "GetHat_json",
            {"HatKodu": line_code},
        )
        if not isinstance(text, str):
            raise IettSoapError("SOAP JSON result was not text")
        return json.loads(text or "[]")

    async def stops_for_line(self, line_code: str) -> list[dict[str, Any]]:
        xml_node = await self._soap_call(
            self.ibb_url,
            "DurakDetay_GYY_wYonAdi",
            {"hat_kodu": line_code},
            raw_xml=True,
        )
        if not isinstance(xml_node, ET.Element):
            return []
        return [self._table_to_dict(table) for table in xml_node.iter() if self._local_name(table.tag) == "Table"]

    async def _soap_call(
        self,
        url: str,
        method: str,
        params: dict[str, str],
        *,
        raw_xml: bool = False,
    ) -> str | ET.Element:
        body = self._soap_body(method, params)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f"http://tempuri.org/{method}",
        }
        await self._rate_limiter.acquire("iett")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "POST",
                    url,
                    content=body,
                    headers=headers,
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "POST",
                url,
                content=body,
                headers=headers,
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        result = self._find_result(root, method)
        if result is None:
            raise IettSoapError(f"SOAP result not found for {method}")
        if raw_xml:
            return result
        return result.text or ""

    def _soap_body(self, method: str, params: dict[str, str]) -> str:
        param_xml = "\n".join(
            f"      <{name}>{html.escape(value)}</{name}>"
            for name, value in params.items()
        )
        return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <{method} xmlns="http://tempuri.org/">
{param_xml}
    </{method}>
  </soap:Body>
</soap:Envelope>"""

    def _find_result(self, root: ET.Element, method: str) -> ET.Element | None:
        expected = f"{method}Result"
        for element in root.iter():
            if self._local_name(element.tag) == expected:
                return element
        return None

    def _table_to_dict(self, table: ET.Element) -> dict[str, Any]:
        return {self._local_name(child.tag): child.text for child in list(table)}

    def _local_name(self, tag: str) -> str:
        return tag.split("}", 1)[-1]
