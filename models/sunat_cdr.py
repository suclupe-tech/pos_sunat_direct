import base64
import io
import re
import zipfile
import xml.etree.ElementTree as ET


class SunatCDR:

    @staticmethod
    def extract_application_response(response_text):
        match = re.search(
            r"<applicationResponse>(.*?)</applicationResponse>",
            response_text,
        )
        return match.group(1) if match else None

    @staticmethod
    def parse_cdr(cdr_base64):
        cdr_zip_bytes = base64.b64decode(cdr_base64)

        cdr_code = ""
        cdr_description = ""

        with zipfile.ZipFile(io.BytesIO(cdr_zip_bytes), "r") as cdr_zip:
            xml_names = [n for n in cdr_zip.namelist() if n.lower().endswith(".xml")]

            if xml_names:
                cdr_xml = cdr_zip.read(xml_names[0])
                root_cdr = ET.fromstring(cdr_xml)

                ns = {
                    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
                }

                response_code_node = root_cdr.find(".//cbc:ResponseCode", ns)
                description_node = root_cdr.find(".//cbc:Description", ns)

                cdr_code = (
                    response_code_node.text if response_code_node is not None else ""
                )
                cdr_description = (
                    description_node.text if description_node is not None else ""
                )

        return {
            "code": cdr_code,
            "description": cdr_description,
        }
