# -*- coding: utf-8 -*-

from odoo import api
from odoo.addons.sale.models.sale_order_line import SaleOrderLine
from odoo.tools import float_compare


@api.depends('display_type', 'product_id')
def _compute_product_uom_qty(self):
    for line in self:
        if line.display_type:
            line.product_uom_qty = 0.0
            continue

        if not line.product_packaging_id:
            continue
        packaging_uom = line.product_packaging_id.product_uom_id
        qty_per_packaging = line.product_packaging_id.qty
        product_uom_qty = packaging_uom._compute_quantity(
            line.product_packaging_qty * qty_per_packaging, line.product_uom)
        if float_compare(product_uom_qty, line.product_uom_qty, precision_rounding=line.product_uom.rounding) != 0:
            line.product_uom_qty = product_uom_qty


setattr(SaleOrderLine, "_compute_product_uom_qty", _compute_product_uom_qty)
