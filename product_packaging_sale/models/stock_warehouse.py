# -*- coding: utf-8 -*-

from odoo import models, fields


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    packaging_product_out_type_id = fields.Many2one("stock.picking.type", string="Packaging Product Out Type",
                                                    domain=[("code", "=", "outgoing")], check_company=True)
