import requests


class SunatClient:

    @staticmethod
    def get_url(mode):
        if mode == "beta":
            return "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"
        return "https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService"

    @staticmethod
    def send_bill(mode, username, password, filename, zip_base64):
        url = SunatClient.get_url(mode)

        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
xmlns:ser="http://service.sunat.gob.pe"
xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<soapenv:Header>
<wsse:Security>
<wsse:UsernameToken>
<wsse:Username>{username}</wsse:Username>
<wsse:Password>{password}</wsse:Password>
</wsse:UsernameToken>
</wsse:Security>
</soapenv:Header>
<soapenv:Body>
<ser:sendBill>
<fileName>{filename}</fileName>
<contentFile>{zip_base64}</contentFile>
</ser:sendBill>
</soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        }

        response = requests.post(
            url,
            data=soap_body.encode("utf-8"),
            headers=headers,
            timeout=60,
        )

        return response.status_code, response.text

    @staticmethod
    def send_summary(mode, username, password, filename, zip_base64):
        url = SunatClient.get_url(mode)

        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
xmlns:ser="http://service.sunat.gob.pe"
xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<soapenv:Header>
<wsse:Security>
<wsse:UsernameToken>
<wsse:Username>{username}</wsse:Username>
<wsse:Password>{password}</wsse:Password>
</wsse:UsernameToken>
</wsse:Security>
</soapenv:Header>
<soapenv:Body>
<ser:sendSummary>
<fileName>{filename}</fileName>
<contentFile>{zip_base64}</contentFile>
</ser:sendSummary>
</soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        }

        response = requests.post(
            url,
            data=soap_body.encode("utf-8"),
            headers=headers,
            timeout=60,
        )

        return response.status_code, response.text

    @staticmethod
    def get_status(mode, username, password, ticket):
        url = SunatClient.get_url(mode)

        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
xmlns:ser="http://service.sunat.gob.pe"
xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<soapenv:Header>
<wsse:Security>
<wsse:UsernameToken>
<wsse:Username>{username}</wsse:Username>
<wsse:Password>{password}</wsse:Password>
</wsse:UsernameToken>
</wsse:Security>
</soapenv:Header>
<soapenv:Body>
<ser:getStatus>
<ticket>{ticket}</ticket>
</ser:getStatus>
</soapenv:Body>
</soapenv:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        }

        response = requests.post(
            url,
            data=soap_body.encode("utf-8"),
            headers=headers,
            timeout=60,
        )

        return response.status_code, response.text

    def action_check_ticket(self):
        for batch in self:

            if not batch.ticket:
                raise Exception("No existe ticket para consultar.")

        first_order = batch.order_ids[0]
        cfg = first_order.session_id.config_id

        username = f"{first_order.company_id.vat}{cfg.sunat_user}"

        status_code, response = SunatClient.get_status(
            cfg.sunat_mode, username, cfg.sunat_password, batch.ticket
        )

        if (
            "0 - La factura ha sido aceptada" in response
            or "aceptad" in response.lower()
        ):
            batch.write({"state": "accepted", "response_message": response})

            batch.order_ids.write(
                {
                    "sunat_state": "aceptado",
                    "sunat_message": "Aceptado vía Resumen Diario",
                }
            )

        else:
            batch.write({"response_message": response})

        return True
