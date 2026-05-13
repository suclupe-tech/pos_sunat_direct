from odoo import models
import io
import re
import base64
import zipfile

from .sunat_summary_builder import SunatSummaryBuilder
from .sunat_signer import SunatSigner
from .sunat_client import SunatClient


class SunatSummaryService(models.AbstractModel):
    _name = "sunat.summary.service"
    _description = "Servicio Resumen Diario SUNAT"

    def send_rc(self, orders):

        if not orders:
            return False

        first_order = orders[0]

        cfg = first_order.session_id.config_id

        rc_id, rc_xml = SunatSummaryBuilder.build_rc_xml(orders)

        rc_signed = SunatSigner.sign_xml(
            rc_xml,
            cfg.sunat_certificate_path,
            cfg.sunat_certificate_password,
        )

        zip_name = f"{first_order.company_id.vat}-{rc_id}.zip"

        mem_zip = io.BytesIO()

        with zipfile.ZipFile(
            mem_zip,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:

            zf.writestr(
                f"{first_order.company_id.vat}-{rc_id}.xml",
                rc_signed,
            )

        zip_binary = base64.b64encode(mem_zip.getvalue())

        username = f"{first_order.company_id.vat}{cfg.sunat_user}"

        status_code, response_text = SunatClient.send_summary(
            cfg.sunat_mode,
            username,
            cfg.sunat_password,
            zip_name,
            zip_binary.decode(),
        )

        match = re.search(r"<ticket>(.*?)</ticket>", response_text)

        if not match:
            raise Exception(f"Sin ticket SUNAT:\n{response_text[:2000]}")

        ticket = match.group(1)

        orders.write(
            {
                "sunat_summary_id": ticket,
                "sunat_summary_filename": zip_name,
                "sunat_summary_file": zip_binary,
                "sunat_summary_xml": rc_signed,
                "sunat_state": "rc_enviado",
                "sunat_message": f"Resumen RC enviado. Ticket={ticket}",
            }
        )

        return ticket
