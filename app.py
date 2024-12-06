from flask import Flask, render_template, request
from datetime import datetime
import asyncio 
import aiohttp

app = Flask(__name__)

WEATHER_API_KEY = '3ce085bb27msha5326b3fbd06a76p1e8ba9jsnd1d9084b630a'
AMADEUS_API_KEY = 'KAquuycU3K2iALIZdQ1OEykJj2AjwqFc'
AMADEUS_API_SECRET = 'ScwBMLGtd1pTzx1X'
TRIPADVISOR_API_KEY = '28DB21DB31E2437EA53EA73A21C31A25'
OPENCAGE_API_KEY = 'c50a386a9f994ecd975f75c8ef514517'

def c_to_f(celsius):   # Converts Celsius formatted temp on WeatherAPI to Farenheit
    return round((celsius * 9/5) + 32, 1) 

def format_date_for_api(input_date):    # Converts YYYY/DD/MM format to standard MM/DD/YYYY format
    return datetime.strptime(input_date, '%m/%d/%Y').strftime('%Y-%m-%d') # String Parse Time

async def get_access_token(session):   # Uses Amadeus API 
    url = "https://api.amadeus.com/v1/security/oauth2/token"
    data = {
        'grant_type': 'client_credentials',
        'client_id': AMADEUS_API_KEY,
        'client_secret': AMADEUS_API_SECRET
    }
    async with session.post(url, data=data) as response:
        return await response.json()


async def get_average_flight_price(session, token, origin, destination, departure_date, num_adults):
    url = "https://api.amadeus.com/v2/shopping/flight-offers"
    headers = {'Authorization': f'Bearer {token}'}
    params = {
        'originLocationCode': origin,
        'destinationLocationCode': destination,
        'departureDate': departure_date,
        'adults': num_adults,
        'max': 5
    }
    async with session.get(url, headers=headers, params=params) as response:
        flight_offers = await response.json()
        prices = [float(offer['price']['total']) for offer in flight_offers.get('data', [])]
        return round(sum(prices) / len(prices), 2) if prices else 0

async def fetch_lat_long(session, city_name):
    url = f"https://api.opencagedata.com/geocode/v1/json"
    params = {'q': city_name, 'key': OPENCAGE_API_KEY}
    async with session.get(url, params=params) as response:
        data = await response.json()
        return data['results'][0]['geometry']['lat'], data['results'][0]['geometry']['lng']

async def fetch_iata_code(session, lat, lng):
    url = "https://api.amadeus.com/v1/reference-data/locations/airports"
    token_data = await get_access_token(session)
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    params = {
        "latitude": lat,
        "longitude": lng,
        "radius": 500
    }
    async with session.get(url, headers=headers, params=params) as response:
        data = await response.json()
        return data['data'][0]['iataCode']
    
async def fetch_weather(session, city, date):
    try:
        # Get coordinates first
        coordinates = await fetch_lat_long(session, city)  # Get coordinates
        
        if not coordinates:
            return (None, None)
            
        lat, lng = coordinates  
        
        url = "https://tomorrow-io1.p.rapidapi.com/v4/weather/forecast"
        
        headers = {
            "x-rapidapi-key": WEATHER_API_KEY,
            "x-rapidapi-host": "tomorrow-io1.p.rapidapi.com"
        }
        
        querystring = {
            "location": f"{lat}, {lng}",  # Use the unpacked coordinates
            "timesteps": "1d",
            "units": "metric"
        }
        
        async with session.get(url, headers=headers, params=querystring) as response:
            data = await response.json()
            
            try:
                # Extract temperature data from the Tomorrow.io response
                daily_data = data['timelines']['daily'][0]
                min_temp_c = daily_data['values']['temperatureMin']
                max_temp_c = daily_data['values']['temperatureMax']
                
                # Convert to Fahrenheit using your existing `c_to_f` function
                return (c_to_f(min_temp_c), c_to_f(max_temp_c))
                
            except KeyError:
                print(f"Failed to extract temperature data for {city}.")
                return (None, None)
                
    except Exception as e:
        print(f"Error in fetch_weather: {e}")
        return (None, None)


async def search_locations(session, destination):
    try:
        url = f"https://api.content.tripadvisor.com/api/v1/location/search"
        params = {
            "key": TRIPADVISOR_API_KEY,
            "searchQuery": ' '.join(destination) if isinstance(destination, list) else destination,
            "language": "en"
        }
        
        async with session.get(url, params=params) as response:
            data = await response.json()
            
            if not data.get('data') or len(data.get('data', [])) == 0:
                return [("No location found", "Unknown City", "Unknown State")]
                
            locations = []
            for loc in data.get('data', [])[:5]:
                name = loc.get('name', 'Unknown Location')
                address_obj = loc.get('address_obj', {})
                city = address_obj.get('city', name)
                state = address_obj.get('state', address_obj.get('country', 'Unknown State'))
                location_id = loc.get('location_id', None)  # Get the location_id
                locations.append((name, city, state, location_id))
                
            return locations if locations else [("No location found", "Unknown City", "Unknown State")]
            
    except Exception as e:
        print(f"Error in search_locations: {str(e)}")
        return [("Error finding location", "Unknown City", "Unknown State")]
    


async def fetch_reviews(session, location_id):
    try:
        url = f"https://api.content.tripadvisor.com/api/v1/location/{location_id}/reviews"
        params = {
            "key": TRIPADVISOR_API_KEY,
            "language": "en"
        }

        async with session.get(url, params=params) as response:
            data = await response.json()

            # Check if we have valid review data
            if data.get('data'):
                reviews = data['data']
                total_rating = sum(review['rating'] for review in reviews) # Calculate the average rating

                average_rating = total_rating / len(reviews)

                
                review_text = reviews[0]['text'] # Get the text of the first review

                return average_rating, review_text
            return 0, "No reviews available for this location."  # Default message if no reviews are found

    except Exception as e:
        print(f"Error fetching reviews: {str(e)}")
        return 0, "Error fetching review."  # Return error message and default average rating



async def fetch_location_photo(session, location_id):
    try:
        url = f"https://api.content.tripadvisor.com/api/v1/location/{location_id}/photos"
        params = {
            "key": TRIPADVISOR_API_KEY,
            "language": "en"
        }

        async with session.get(url, params=params) as response:
            data = await response.json()

            if data.get('data'):
                first_photo = data['data'][0] 
                photo_url = first_photo['images']['large']['url']
                return photo_url
            return None 

    except Exception as e:
        print(f"Error fetching photo: {str(e)}")
        return None 

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    start_location = request.form['start_location']
    keywords = request.form['destination']
    check_in = request.form['check-in']
    num_adults = request.form['num_adults']
    departure_date = format_date_for_api(check_in)

    async def fetch_all_data(destination, start_location, departure_date, num_adults):
        async with aiohttp.ClientSession() as session:
            token_data = await get_access_token(session)

            locations_task = search_locations(session, keywords.split(","))
            top_locations = await locations_task

            # Unpack 4 values (name, city, state, location_id) from top_locations
            chosen_location_name, chosen_city, chosen_state, location_id = top_locations[0]

            # Fetch reviews asynchronously
            reviews_task = fetch_reviews(session, location_id)

            # Fetch latitude and longitude for the chosen city
            destination_lat, destination_lng = await fetch_lat_long(session, chosen_city)
            start_lat, start_lng = await fetch_lat_long(session, start_location)

            # Fetch IATA codes
            start_iata_code = await fetch_iata_code(session, start_lat, start_lng)
            destination_iata_code = await fetch_iata_code(session, destination_lat, destination_lng)

            # Fetch weather and flight prices
            weather_task = fetch_weather(session, chosen_city, departure_date)
            flight_price_task = get_average_flight_price(session, token_data['access_token'], start_iata_code, destination_iata_code, departure_date, num_adults)

            # Fetch location photo
            photo_task = fetch_location_photo(session, location_id)

            avg_temp_low_f, avg_temp_high_f = await weather_task
            avg_flight_price = await flight_price_task
            average_rating, review_text = await reviews_task  
            location_photo_url = await photo_task 

            # Return the data we want
            return (chosen_location_name, chosen_city, chosen_state, avg_temp_low_f, avg_temp_high_f, avg_flight_price, 
                    average_rating, review_text, location_photo_url, top_locations)

    # Run the async function in a synchronous context
    data = asyncio.run(fetch_all_data(keywords, start_location, departure_date, num_adults))

    (chosen_location_name, chosen_city, chosen_state, avg_temp_low_f, avg_temp_high_f, avg_flight_price, 
     average_rating, review_text, location_photo_url, additional_suggestions) = data

    # Pass the data along with the form values to the template
    return render_template('results.html', 
                           location_name=chosen_location_name,
                           city=chosen_city, 
                           state=chosen_state, 
                           check_in=check_in,
                           avg_temp_low_f=avg_temp_low_f, 
                           avg_temp_high_f=avg_temp_high_f,
                           avg_flight_price=avg_flight_price,
                           average_rating=average_rating,  # Pass the average rating to the template
                           review_text=review_text,  # Pass the review text to the template
                           location_photo_url=location_photo_url,  # Pass the photo URL to the template
                           additional_suggestions=additional_suggestions,
                           start_location=start_location, 
                           keywords=keywords,
                           num_adults=num_adults)

if __name__ == '__main__':
    app.run(debug=True)