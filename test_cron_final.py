
import sys
import logging
from datetime import datetime, timedelta

# Force UTF-8 for output
sys.stdout.reconfigure(encoding='utf-8')

def test_cron_logic():
    print("=== START TEST CRON LOGIC ===")
    
    # Enable logging
    logging.getLogger('odoo.addons.student_request.models.service').setLevel(logging.INFO)
    
    RequestModel = env['student.service.request']
    StepModel = env['student.service.request.step']
    
    # 1. Find a target step to test (e.g., Step 78)
    step = StepModel.browse(78)
    if not step.exists():
        print("Step 78 not found. Searching for any closed step...")
        step = StepModel.search([('state', '=', 'closed')], limit=1)
        
    if step:
        print(f"Testing with Step [{step.id}]")
        
        # 2. Reset step to 'assigned' using ORM first
        print("Resetting step to 'assigned'...")
        service = step.request_id.service_id
        if service.rating_timeout <= 0:
             service.write({'rating_timeout': 1})
             
        step.write({
            'state': 'assigned'
        })
        env.cr.commit() # Commit Odoo write
        
        # Use SQL to force write_date to past
        print("Forcing write_date to past via SQL...")
        past_date = datetime.now() - timedelta(minutes=100)
        print(f"  Target Past Date: {past_date}")
        
        env.cr.execute("UPDATE student_service_request_step SET write_date = %s WHERE id = %s", (past_date, step.id))
        env.cr.commit() # Commit SQL write
        
        step.invalidate_recordset()
        
        # Verify date in DB
        env.cr.execute("SELECT write_date FROM student_service_request_step WHERE id = %s", (step.id,))
        db_date = env.cr.fetchone()[0]
        print(f"  DB Date after SQL: {db_date}")
        
        print(f"Step state after reset: {step.state}")
        
        # 3. Run Cron
        print("Running cron...")
        try:
            RequestModel._cron_auto_complete_rating()
            
            # 4. Verify
            step.invalidate_recordset() # Refresh cache
            print(f"Step state after cron: {step.state}")
            if step.state == 'closed':
                print("SUCCESS: Step was auto-closed!")
            else:
                print("FAILURE: Step did not close.")
                # Debug why
                deadline = datetime.now() - timedelta(minutes=service.rating_timeout)
                print(f"  Deadline: {deadline}")
                print(f"  Write Date: {step.write_date}")
                print(f"  Step Name: {step.selection_id.step_name}")
                
        except Exception as e:
            print(f"ERROR running cron: {e}")
            import traceback
            traceback.print_exc()
            
    else:
        print("No suitable step found to test.")

    print("=== END TEST CRON LOGIC ===")

test_cron_logic()
