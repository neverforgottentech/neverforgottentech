# check_profile.py
from memorials.models import Memorial
import requests

print('=== Investigating Memorial ID: 2 ===')
try:
    m = Memorial.objects.get(id=2)
    print(f'1. Profile picture field value: {m.profile_picture}')
    
    if hasattr(m.profile_picture, 'url'):
        stored_url = m.profile_picture.url
        print(f'2. Generated URL: {stored_url}')
        
        print('3. Testing URL accessibility...')
        try:
            response = requests.head(stored_url, timeout=5)
            print(f'   Status Code: {response.status_code}')
            if response.status_code == 200:
                print('   ✓ URL is accessible.')
            elif response.status_code == 404:
                print('   ✗ Error 404: File not found on Cloudinary.')
            else:
                print(f'   ⚠️ Unexpected status: {response.status_code}')
        except Exception as e:
            print(f'   ✗ Failed to reach URL: {e}')
    else:
        print('2. The profile_picture field does not have a .url method.')
        print(f'   Field type: {type(m.profile_picture)}')
        
except Memorial.DoesNotExist:
    print('✗ Memorial with ID=2 does not exist')
except Exception as e:
    print(f'✗ Error: {e}')
    
print('=== Diagnostic Complete ===')