##############################################################################
#    
#    OpenERP, Open Source Management Solution
#    Copyright (C) 
#    2004-2010 Tiny SPRL (<http://tiny.be>). 
#    2009-2010 Veritos (http://veritos.nl).
#    2013 Solnet Solutions Limited (http://solnetsolutions.co.nz
#    All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import osv, fields
import logging

class account_invoice_refund(osv.osv_memory):
    
    _inherit = "account.invoice.refund"
    
    def compute_refund(self, cr, uid, ids, mode='refund', context=None):
        invoice_obj = self.pool.get('account.invoice')
        invoice_line_obj = self.pool.get('account.invoice.line')
        
        result = super(account_invoice_refund, self).compute_refund(cr, uid, ids, mode, context=context)
        # for a financial credit each invoice line should be based on the imput and output
        invoice_tuple_ids = result.values()[1][1]
        invoice_ids = invoice_obj.search(cr, uid, [(invoice_tuple_ids)], context=context)
        for invoice in invoice_ids:
            invoice_record = invoice_obj.browse(cr, uid, invoice, context=context)
            invoice_lines = invoice_line_obj.search(cr, uid, [('invoice_id','=', invoice)], context = context)
            for line in invoice_lines:
                line_record = invoice_line_obj.browse(cr, uid, line, context = context)
                if line_record.product_id:
                    account = line_record.product_id.product_tmpl_id.property_account_expense.id
                    if not account:
                        account = line_record.product_id.categ_id.property_account_expense_categ.id
                    
                    if account:
                        invoice_line_obj.write(cr, uid, line_record.id,
                                {"account_id": account}, context = context)   
        return result
        
        
        
        
        
account_invoice_refund()