/** @odoo-module */
import {patch} from "@web/core/utils/patch";
import {PosOrder} from "@point_of_sale/app/models/pos_order";
import {PaymentScreen} from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { useState } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";


patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);

        this.sunat_document_type = vals?.sunat_document_type || "03";
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.sunat_document_type = this.sunat_document_type || "03";

        return json;

    },
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);

        this.sunat_document_type = json.sunat_document_type || "03";
    },

    set_sunat_document_type(type) {
        this.sunat_document_type = type;
    },

    get_sunat_document_type() {
        return this.sunat_document_type || "03";
    },
});

patch(PaymentScreen.prototype, {
    setup() {
        super.setup();

        this.state = useState({sunat_document_type: this.currentOrder.get_sunat_document_type(),});
    },
    setDocumentType(type) {
        this.state.sunat_document_type = type;
        this.currentOrder.set_sunat_document_type(type);
    },
});

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        const tipo = this.currentOrder.get_sunat_document_type();
        const cliente = this.currentOrder.getPartner();

        // Bloquear FACTURACION INTERNA DE ODOO
        order.setToInvoice(false);

        //validacion factura sunat
        if (tipo === "01") {
            if (!cliente || !cliente.vat || cliente.vat.trim().length !== 11) {
                this.dialog.add(AlertDialog, {
                    title: "Factura inválida",
                    body: "Debe seleccionar un cliente con RUC para emitir factura.",
                });
                return;
            }
        }

        return super.validateOrder(...arguments);
    },
});