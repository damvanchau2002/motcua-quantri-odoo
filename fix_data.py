
import sys
import logging

# Force UTF-8 for output
sys.stdout.reconfigure(encoding='utf-8')

def fix_data():
    print("=== START FIX DATA ===")
    State = env['student.service.request.state']
    
    # Check if 'rating' state exists
    rating_state = State.search([('type', '=', 'rating')])
    if not rating_state:
        print("Creating missing 'rating' state...")
        try:
            State.create({
                'name': 'Đánh giá chất lượng',
                'code': 'rating',
                'type': 'rating',
                'sequence': 90,
                'color': 3, # Yellow/Orange usually
                'description': 'Trạng thái chờ sinh viên đánh giá chất lượng dịch vụ'
            })
            print("  Created successfully.")
            env.cr.commit()
        except Exception as e:
            print(f"  Error creating state: {e}")
            env.cr.rollback()
    else:
        print(f"  'rating' state already exists: {rating_state.name}")

    print("=== END FIX DATA ===")

fix_data()
