from odoo import models, fields
from odoo.exceptions import UserError


class SunatCreditNoteWizard(models.TransientModel):
    _name = "sunat.credit.note.wizard"
    _description = "Asistente Nota de Crédito SUNAT"

    order_id = fields.Many2one(
        "pos.order",
        string="Orden POS original",
        required=True,
        readonly=True,
    )

    sunat_document_number = fields.Char(
        string="Documento original",
        related="order_id.sunat_document_number",
        readonly=True,
    )

    sunat_document_type = fields.Selection(
        related="order_id.sunat_document_type",
        string="Tipo documento original",
        readonly=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        related="order_id.currency_id",
        readonly=True,
    )

    amount_total = fields.Monetary(
        string="Total original",
        related="order_id.amount_total",
        currency_field="currency_id",
        readonly=True,
    )

    reason_code = fields.Selection(
        [
            ("01", "Anulación de la operación"),
            ("06", "Devolución total"),
            ("07", "Devolución parcial"),
        ],
        string="Motivo Nota de Crédito",
        required=True,
        default="01",
    )

    reason_description = fields.Text(
        string="Descripción / Sustento",
        default="Regularización por error de digitación.",
    )

    def action_confirm_credit_note(self):
        self.ensure_one()

        order = self.order_id

        if not order:
            raise UserError("No se encontró la orden original.")

        if order.sunat_state != "aceptado":
            raise UserError(
                "Solo se puede crear Nota de Crédito de documentos aceptados por SUNAT."
            )

        if order.sunat_document_type not in ("01", "03"):
            raise UserError(
                "Solo se puede crear Nota de Crédito desde Factura o Boleta."
            )

        if not order.sunat_document_number:
            raise UserError("La orden no tiene número de documento SUNAT.")

        refund_orders = self.env["pos.order"]

        # 1. Intentar usar refund_order_ids si existe
        if "refund_order_ids" in order._fields:
            refund_orders = order.refund_order_ids

        # 2. Si no encuentra, buscar por nombre de reembolso
        if not refund_orders:
            refund_orders = self.env["pos.order"].search(
                [
                    ("name", "ilike", "REEMBOLSO DE " + order.name),
                    ("amount_total", "<", 0),
                ]
            )

        # 3. Si tampoco encuentra, buscar por referencia POS
        if not refund_orders and order.pos_reference:
            refund_orders = self.env["pos.order"].search(
                [
                    ("name", "ilike", "REEMBOLSO"),
                    ("pos_reference", "ilike", order.pos_reference),
                    ("amount_total", "<", 0),
                ]
            )

        refund_orders = refund_orders.filtered(lambda r: r.amount_total < 0)

        if not refund_orders:
            raise UserError(
                "No se encontró un reembolso relacionado a esta orden.\n\n"
                "Por ahora primero debes crear el reembolso con el botón 'Devolver productos'. "
                "Luego vuelve a este menú para marcarlo como Nota de Crédito SUNAT."
            )

        refund_order = refund_orders[0]

        # ==========================================================
        # EVITAR NOTAS DE CRÉDITO DUPLICADAS
        #
        # Si el reembolso ya fue convertido en Nota de Crédito y
        # tiene numeración SUNAT, no se debe limpiar ni generar otra.
        # ==========================================================
        if (
            refund_order.sunat_document_type == "07"
            and refund_order.sunat_document_number
        ):
            if (
                refund_order.sunat_state == "aceptado"
                or refund_order.sunat_cdr_code == "0"
            ):
                raise UserError(
                    f"Este reembolso ya tiene la Nota de Crédito "
                    f"{refund_order.sunat_document_number} aceptada por SUNAT. "
                    "No se generará otra Nota de Crédito."
                )

            raise UserError(
                f"Este reembolso ya tiene la Nota de Crédito "
                f"{refund_order.sunat_document_number} con estado "
                f"{refund_order.sunat_state}. "
                "No se generará una nueva numeración. "
                "Revisa la Nota de Crédito existente para continuar con su envío."
            )

        refund_order.write(
            {
                "sunat_document_type": "07",
                "sunat_origin_order_id": order.id,
                "sunat_origin_document_type": order.sunat_document_type,
                "sunat_origin_document_number": order.sunat_document_number,
                "sunat_credit_note_reason_code": self.reason_code,
                "sunat_state": "borrador_nota_credito",
                "sunat_message": "Reembolso marcado como Nota de Crédito SUNAT. Falta generar XML tipo 07.",
                # Limpiar datos SUNAT anteriores porque el reembolso pudo haberse generado como Boleta
                "sunat_document_number": False,
                "sunat_xml": False,
                "sunat_xml_filename": False,
                "sunat_xml_file": False,
                "sunat_zip_filename": False,
                "sunat_zip_file": False,
                "sunat_cdr_filename": False,
                "sunat_cdr_file": False,
                "sunat_cdr_code": False,
                "sunat_cdr_description": False,
                "sunat_summary_filename": False,
                "sunat_summary_file": False,
                "sunat_summary_xml": False,
                "sunat_summary_id": False,
                "sunat_rc_batch_id": False,
            }
        )

        # ==========================================================
        # GENERACIÓN Y ENVÍO AUTOMÁTICO DE LA NOTA DE CRÉDITO
        #
        # Una vez que el reembolso fue convertido en Nota de Crédito:
        # 1. Genera y firma el XML tipo 07.
        # 2. Verifica que el XML se haya generado correctamente.
        # 3. Envía la Nota de Crédito directamente a SUNAT.
        # 4. SUNAT devolverá el CDR y actualizará el estado.
        # ==========================================================

        refund_order.action_generate_sunat_xml()

        # action_generate_sunat_xml captura internamente los errores,
        # por eso verificamos el resultado antes de intentar enviarlo.
        if refund_order.sunat_state == "xml_firmado" and refund_order.sunat_xml:
            refund_order.action_send_sunat()

        return {
            "type": "ir.actions.act_window",
            "name": "Nota de Crédito SUNAT",
            "res_model": "pos.order",
            "view_mode": "form",
            "res_id": refund_order.id,
            "target": "current",
        }
