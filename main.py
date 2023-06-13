import os, json, requests, time, re, telebot, sqlite3, pytz
from google.cloud import dialogflow_v2beta1 as dialogflow
from google.cloud.dialogflow_v2beta1.types.session import QueryResult
from google.protobuf.json_format import MessageToDict
from google.api_core.exceptions import InvalidArgument
from telebot import types
from datetime import datetime
from threading import Thread
from fuzzywuzzy import fuzz, process
from unidecode import unidecode
from apscheduler.schedulers.blocking import BlockingScheduler

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = 'private_key.json'

DIALOGFLOW_PROJECT_ID = 'tsisupportbot-ksyr'
DIALOGFLOW_LANGUAGE_CODE = 'en'
SESSION_ID = 'me'

# Set up your SQLite database
DATABASE_FILE = "students.db"

# Set up your bot's API token
TOKEN = os.getenv('TSI_BOT_KEY')

# Create an instance of the bot
bot = telebot.TeleBot(TOKEN)

# API URLs
items_url = 'https://services.tsi.lv/schedule/api/service.asmx/GetItems?'
contacts_url = 'http://services-api.tsi.lv:3000/contacts'
schedule_url = 'https://services.tsi.lv/schedule/api/service.asmx/GetLocalizedEvents?'

# Define a global variable to store the values dictionary
items = {}

# ascii teachers names
unidecode_teachers = []

# Define the list of possible keys for the start and end dates
start_date_keys = ['startTime', 'startDate', 'startDateTime']
end_date_keys = ['endTime', 'endDate', 'endDateTime']

# Define fuzzy match score
match_score = 70


# Handle the "/start" command
@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, '''Hi there! I'm your personal university assistant. I'm here to help you stay on top of your academic life.

To get started, select your group number by using /selectgroup command or just by asking me to change it and I'll keep you updated on your schedule and important deadlines. If you ever need to change your group or check your schedule, just let me know.

Don't hesitate to ask me anything related to your studies. I'm here to help you succeed! 🎓🤖''')


# Define a function to fill the items dictionary with the latest values from the API
def fill_items_dict():
    global items

    try:
        # Make a request to the values API and store the response as a dictionary
        response = requests.get(items_url)
        string_data = response.content.decode('utf-8')[1:-1].replace(')(', '')
        content = json.loads(string_data)
        data = content.get('d')
        new_items = json.loads(data)
        if new_items:
            if not new_items == items:
                items = new_items
                json.dump(new_items, open('items.json', 'w'), indent=4, ensure_ascii=False)
                print('Successfully saved items')
                fill_groups_table()
            else:
                print('No new items')
        else:
            print('Received empty Items')
    except Exception as e:
        # Handle any exceptions that might be raised during the execution of the function
        print(f"Error: {e}")


# Function to fill available_groups table with group numbers from an API
def fill_groups_table():
    if items.get('groups'):
        # If the request is successful, parse the response JSON to extract group numbers
        groups = items['groups'].values()

        # Create a new connection and cursor object
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()

        # Clear any existing data from the available_groups table
        c.execute("DELETE FROM groups")

        # Insert the new groups into the available_groups table
        for group in groups:
            c.execute("INSERT INTO groups (group_number) VALUES (?)", (group,))

        # Commit the changes to the database
        conn.commit()
        print("Groups table updated successfully.")
    else:
        # If the request fails, log an error message
        print("Failed to retrieve groups from items.")


def timed_update():
    print(datetime.now().strftime('%d.%m.%Y - %H:%M:%S'))


def background_tasks():
    scheduler = BlockingScheduler()
    scheduler.add_job(timed_update, trigger="interval", minutes=1)
    scheduler.add_job(fill_items_dict, trigger="interval", hours=1)
    scheduler.start()


    def map_event(event):
        # Replace the room ID with its corresponding value
        room_id = event[1][0] if len(event[1]) > 0 else None
        room_value = items["rooms"].get(str(room_id), "Not specified")
        event[1] = room_value

        # Replace the group IDs with their corresponding values
        group_ids = event[2]
        group_values = [items["groups"].get(str(group_id), "") for group_id in group_ids]
        event[2] = group_values

        # Replace the teacher ID with its corresponding value
        teacher_id = event[3]
        teacher_value = items["teachers"].get(str(teacher_id), "")
        event[3] = teacher_value

        return event


def check_items():
    # Set the API endpoint URL
    # url = "https://services.tsi.lv/schedule/api/service.asmx/GetLocalizedEvents?from=1674649373&to=1677327773&teachers=&rooms=&groups=&lang=%27en%27"
    url = "https://services.tsi.lv/schedule/api/service.asmx/GetLocalizedEvents?from=1676476800&to=1676484900&teachers=&rooms=&groups=&lang=%27en%27"

    # Set any required query parameters for the API request
    params = {
        "parameter1": "value1",
        "parameter2": "value2"
    }

    # Send an HTTP GET request to the API endpoint with the query parameters
    response = requests.get(url, params=params)
    string_data = response.content.decode('utf-8')[1:-1].replace(')(', '')
    a = json.loads(string_data)
    data = json.loads(a.get('d'))
    print(data)
    print(json.dumps(data, indent=4, ensure_ascii=False))

    events = data['events']['values']
    mapped_events = [map_event(event) for event in events]

    message = ''
    last_date = None
    for event in mapped_events:
        dt_object = datetime.fromtimestamp(event[0])
        date_string = dt_object.strftime("%d.%m.%Y")
        time_string = dt_object.strftime("%H:%M")
        room = event[1][0] if len(event[1]) > 0 else 'TBA'
        groups = ", ".join(event[2]) if len(event[2]) > 0 else 'Not specified'
        teacher = event[3]
        name = event[4]

        if not last_date == date_string:
            last_date = date_string
            message += f'{date_string}\n\n'

        message += f'{name} with {teacher}\nRoom: {room}\nGroups: {groups}\nTime: {time_string}\n\n'

    if not message:
        # If there are no events for the given group, return a message indicating this
        message = 'No events found for this group.'

    print(message)


def get_student_group(chat_id):
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()

    # Check if the user has already selected a group
    c.execute("SELECT * FROM students WHERE chat_id = ?", (chat_id,))
    rows = c.fetchall()
    return rows[0][1] if rows else None


# Handle the "/selectgroup" command
@bot.message_handler(commands=['selectgroup'])
def select_group(message):
    group = get_student_group(message.chat.id)

    if group:
        # If the user has already selected a group, include it in the message and give them an option to cancel the command
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton("Cancel"))
        bot.send_message(chat_id=message.chat.id, text=f"Your current group is {group}.\nPlease enter your new group number:", reply_markup=keyboard)
        bot.register_next_step_handler(message, set_group)
    else:
        # If the user has not yet selected a group, ask them to provide their group number
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton("Cancel"))
        bot.send_message(chat_id=message.chat.id, text="Please enter your group number:", reply_markup=keyboard)
        bot.register_next_step_handler(message, set_group)


# Handler to receive the user's group number and store it in the database
def set_group(message):
    # Retrieve the group number from the user's message
    group = message.text.upper()

    if group == "CANCEL":
        # If the user chooses to cancel the command, clear the keyboard and end the conversation
        hide_keyboard = types.ReplyKeyboardRemove()
        bot.send_message(chat_id=message.chat.id, text="Canceled", reply_markup=hide_keyboard)
        return

    # Create a new connection and cursor object
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()

    # Query the database for groups that match the user's input
    c.execute("SELECT * FROM groups WHERE group_number = ?", (group,))
    rows = c.fetchall()

    if len(rows) == 0:
        # If the entered group number is not valid, send a message with available groups that match the user's input
        c.execute("SELECT DISTINCT group_number FROM groups WHERE group_number LIKE ?", ('%' + group + '%',))
        rows = c.fetchall()
        if len(rows) > 0:
            # If there are available groups that match the user's input, send a message with keyboard keys containing the available groups
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for row in rows:
                keyboard.add(types.KeyboardButton(row[0]))

            keyboard.add(types.KeyboardButton("Cancel"))
            bot.send_message(chat_id=message.chat.id, text="Sorry, the entered group number is not valid. Please select your group from the following options:", reply_markup=keyboard)
            # Set up a handler to receive the user's selection
            bot.register_next_step_handler(message, set_group_keyboard)
        else:
            # If there are no available groups that match the user's input, ask the user to try again
            bot.send_message(chat_id=message.chat.id, text="Sorry, no groups were found that match your input. Please try again.")
            select_group(message)
    else:
        # Check if the user has already selected a group
        c.execute("SELECT * FROM students WHERE chat_id = ?", (message.chat.id,))
        rows = c.fetchall()

        if len(rows) > 0:
            # If the user has already selected a group, update their group value in the database
            c.execute("UPDATE students SET group_number = ? WHERE chat_id = ?", (group, message.chat.id))
            conn.commit()
            # Send a confirmation message to the user
            hide_keyboard = types.ReplyKeyboardRemove()
            bot.send_message(chat_id=message.chat.id, text=f"Your group {group} has been updated successfully!", reply_markup=hide_keyboard)
        else:
            # If the user has not yet selected a group, insert a new row with their chat ID and group number
            c.execute("INSERT INTO students (chat_id, group_number) VALUES (?, ?)", (message.chat.id, group))
            conn.commit()
            # Send a confirmation message to the user
            hide_keyboard = types.ReplyKeyboardRemove()
            bot.send_message(chat_id=message.chat.id, text=f"Your group {group} has been set successfully!", reply_markup=hide_keyboard)


# Handler to receive the user's selection from the keyboard and call the set_group function
def set_group_keyboard(message):
    set_group(message)


# Handler to search for the user's group based on a search term
def search_groups(message):
    # Retrieve the user's search term
    search_term = message.text.lower()

    # Create a new connection and cursor object
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()

    # Query the database for groups matching the search term
    c.execute("SELECT DISTINCT group_number FROM students WHERE group_number LIKE ?", ('%' + search_term + '%',))
    rows = c.fetchall()

    if len(rows) == 0:
        # If no matching groups were found, ask the user to try again
        bot.send_message(chat_id=message.chat.id, text="No groups matching your search were found. Please try again.")
        select_group(message)

    elif len(rows) == 1:
        # If only one matching group was found, store it in the database and send a confirmation message to the user
        group = rows[0][0]
        c.execute("INSERT INTO students (chat_id, group_number) VALUES (?, ?)", (message.chat.id, group))
        conn.commit()
        bot.send_message(chat_id=message.chat.id, text="Your group has been saved. Thank you!")

    else:
        # If multiple matching groups were found, send a list of options to the user
        options = [row[0] for row in rows]
        options_str = "\n".join(options)
        bot.send_message(chat_id=message.chat.id, text="Multiple groups were found. Please select your group from the list:\n\n" + options_str)

        # Set up a handler to receive the user's selection
        bot.register_next_step_handler(message, set_group)


# Define a function to extract the start date from a dictionary of parameters
def extract_start_date(parameters):
    for key in start_date_keys:
        start_date = parameters.get(key)
        if start_date:
            break
    return start_date


# Define a function to extract the end date from a dictionary of parameters
def extract_end_date(parameters):
    for key in end_date_keys:
        end_date = parameters.get(key)
        if end_date:
            break
    return end_date


def find_group_key(group_text):
    for key, value in items.get('groups').items():
        if value == group_text:
            return key

    return None


def find_teacher_key(teacher_text):
    for key, value in items.get('teachers').items():
        if value == teacher_text:
            return key

    return None


# Define a function to fuzzy match a search string to a teacher name
def match_teacher(search_string):

    # print(search_string)

    teacher_names = items.get('teachers')
    if teacher_names:
        teacher_names = [t for t in list(teacher_names.values())]
    else:
        print('Error no teachers')
        return None

    # Check if there are multiple matches with the same score
    fuzzy_matches = process.extract(search_string, teacher_names, limit=20)
    unidecode_matches = process.extract(search_string, unidecode_teachers, limit=20)

    partial_matches = []

    if len(fuzzy_matches) > 1:
        # print(fuzzy_matches)
        fuzzy_matches = [result[0] for result in fuzzy_matches if result[1] == fuzzy_matches[0][1]]
        # print(fuzzy_matches)
        for m in fuzzy_matches:
            score_1 = fuzz.ratio(m.split()[0], search_string)
            score_2 = fuzz.ratio(m.split()[1], search_string)
            if score_1 > match_score or score_2 > match_score:
                print(m, search_string, score_1 if score_1 > score_2 else score_2)
                partial_matches.append(m)

    if len(unidecode_matches) > 1:
        unidecode_matches = [result[0] for result in unidecode_matches if result[1] == unidecode_matches[0][1]]

        for m in unidecode_matches:
            teacher_name = teacher_names[unidecode_teachers.index(m)]
            score_1 = fuzz.ratio(m.split()[0], search_string)
            score_2 = fuzz.ratio(m.split()[1], search_string)
            if (score_1 > match_score or score_2 > match_score) and teacher_name not in partial_matches:
                print(teacher_name, search_string, score_1 if score_1 > score_2 else score_2)
                partial_matches.append(teacher_name)

    if len(partial_matches) > 1:
        return partial_matches
    elif len(partial_matches) == 1:
        return partial_matches[0]
    else:
        return None


def check_schedule(message, parameters):
    dt_datetime, dt_start, dt_end = None, None, None

    date_data = parameters.get('date-time')
    if not date_data:
        date_data = parameters.get('date-period')
    if not date_data:
        date_data = datetime.today().strftime('%Y-%m-%dT%H:%M:%S%z') + '+02:00'

    # Parse the datetime string
    if date_data:
        if type(date_data) is dict:
            if date_data.get('date_time'):
                dt_datetime = datetime.strptime(date_data.get('date_time'), '%Y-%m-%dT%H:%M:%S%z')
            else:
                dt_start = datetime.strptime(extract_start_date(date_data), '%Y-%m-%dT%H:%M:%S%z')
                dt_end = datetime.strptime(extract_end_date(date_data), '%Y-%m-%dT%H:%M:%S%z')
        elif type(date_data) is str:
            dt_datetime = datetime.strptime(date_data, '%Y-%m-%dT%H:%M:%S%z')

    if dt_datetime:
        bot.send_message(message.chat.id, f'{dt_datetime.strftime("%d.%m.%Y")}')
    elif dt_start and dt_end:
        bot.send_message(message.chat.id, f'Start: {dt_start.strftime("%d.%m.%Y %H:%M")}\nEnd: {dt_end.strftime("%d.%m.%Y %H:%M")}')
    else:
        bot.send_message(message.chat.id, f'Unrecognised time period:\n\n{parameters}')
        return

    # Get all teachers that message contains
    matching_teachers = []

    for t in message.text.split():
        matches = match_teacher(t)
        if type(matches) == str:
            matching_teachers.append(matches)
        elif type(matches) == list:
            matching_teachers = matching_teachers + matches
        elif not matches:
            pass
        else:
            print(f'Unrecognized type({type(matches)})')

    matching_teachers = set(matching_teachers)

    print('Teachers:')
    for t in matching_teachers:
        print(t)

    if parameters.get('group-text'):
        group_text = parameters.get('group-text')
    else:
        group_text = get_student_group(message.chat.id)

    group_number = find_group_key(group_text)

    if not group_text:
        bot.send_message(message.chat.id, 'Please specify at least one group')
        return
    elif not group_number:
        bot.send_message(message.chat.id, f'''Couldn't find group {group_text}''')
        bot.delete_message(message.chat.id, message.id)
        return

    # Use a regular expression to split the group into a numeric part and a letter part
    match = re.match(r'(\d+)-?(\w+)', group_text)
    if match:
        numeric_part = match.group(1)
        letter_part = match.group(2)

        # Use the numeric and letter parts to filter the list of groups
        matching_groups = [group for group in items.get('groups').values() if re.match(r'^\d{}.*{}$'.format(numeric_part[1:2], letter_part), group)]

        # Print the resulting list of matching groups
        # for group in matching_groups:
        #     print(group)

    else:
        print('Invalid group number')


    # Set any required query parameters for the API request
    params = {
        'groups': f'\'{",".join([find_group_key(x) for x in matching_groups])}\'' if matching_groups else '',
        'teachers': f'\'{",".join([find_teacher_key(x) for x in matching_teachers])}\'' if matching_teachers else '',
        'lang': '\'en\''
    }

    from_time, to_time = 0, 0

    if dt_datetime:
        from_time = int(dt_datetime.replace(hour=0, minute=0).timestamp())
        to_time = int(dt_datetime.replace(hour=23, minute=59).timestamp())
    elif dt_start and dt_end:
        from_time = int(dt_start.timestamp())
        to_time = int(dt_end.timestamp())

    params['from'] = from_time
    params['to'] = to_time

    print(json.dumps(params, indent=4))

    url = "https://services.tsi.lv/schedule/api/service.asmx/GetLocalizedEvents?&rooms="

    # Send an HTTP GET request to the API endpoint with the query parameters
    response = requests.get(url, params=params)
    if response.status_code == 200:
        string_data = response.content.decode('utf-8')[1:-1].replace(')(', '')
        a = json.loads(string_data)
        data = json.loads(a.get('d'))
        print(data)
        # print(json.dumps(data, indent=4, ensure_ascii=False))

        if data.get('events'):

            events = data['events']['values']

            # Filter the list of events to only those with the desired group number
            filtered_events = [event for event in events if int(group_number) in event[2]]

            mapped_events = [map_event(event) for event in filtered_events]
            print(len(mapped_events))

            schedule_text = ''
            last_date = None
            for event in mapped_events:
                dt_object = datetime.utcfromtimestamp(event[0]).replace(tzinfo=pytz.UTC)
                # Convert the UTC datetime object to Europe/Riga timezone
                local_datetime = dt_object.astimezone(pytz.timezone('Etc/GMT+0'))
                date_string = dt_object.strftime("%d.%m.%Y")
                time_string = local_datetime.strftime("%H:%M")
                room = event[1] if event[1] else 'Not specified'
                groups = ", ".join(event[2]) if len(event[2]) > 0 else 'Not specified'
                teacher = event[3].strip()
                name = event[4].strip()

                if not last_date == date_string:
                    last_date = date_string
                    schedule_text += f'{date_string}\n\n'

                if len(str(schedule_text + f'{name} with {teacher}\nRoom: {room}\nGroups: {groups}\nTime: {time_string}\n\n')) > 4096:
                    bot.send_message(message.chat.id, schedule_text)
                    schedule_text = ''

                schedule_text += f'{name} with {teacher}\nRoom: {room}\nGroups: {groups}\nTime: {time_string}\n\n'
            if not schedule_text:
                # If there are no events for the given group, return a message indicating this
                schedule_text = f'No events found for group {group_text}.'

            # Send the schedule back to the user
            bot.send_message(message.chat.id, schedule_text)

        elif data.get('Message'):
            bot.send_message(message.chat.id, data.get('Message'))
        else:
            bot.send_message(message.chat.id, 'An error occurred. Please kindly send this to the developer.')
    else:
        print(response.content)
        print(response.status_code)
        bot.send_message(message.chat.id, 'An error occurred. Please kindly send this to the developer.')



def check_lecturer_contact(message):
    # Retrieve the lecturer name parameter from the user's message
    lecturer_name = message.text.split(" ")[1]

    # Call your function to retrieve the contact information for the specified lecturer
    contact_info = get_lecturer_contact(lecturer_name)

    # Send the contact information back to the user
    bot.reply_to(message, contact_info)


# Handle plain text messages
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text_to_be_analyzed = message.text

    session_client = dialogflow.SessionsClient()
    session = session_client.session_path(DIALOGFLOW_PROJECT_ID, SESSION_ID)
    text_input = dialogflow.types.TextInput(text=text_to_be_analyzed, language_code=DIALOGFLOW_LANGUAGE_CODE)
    query_input = dialogflow.types.QueryInput(text=text_input)
    try:
        response = session_client.detect_intent(session=session, query_input=query_input)
    except InvalidArgument:
        raise

    query_result_dict = MessageToDict(response._pb)
    intent = query_result_dict.get('queryResult').get('intent').get('displayName')
    # print(json.dumps(query_result_dict.get('queryResult'), indent=4))

    print("Detected intent:", intent)
    print("Detected parameters:\n", json.dumps(dict(query_result_dict.get('queryResult').get('parameters')), indent=4))
    print("Detected intent confidence:", query_result_dict.get('queryResult').get('intent_detectionConfidence'))
    print("Fulfillment text:", query_result_dict.get('queryResult').get('fulfillmentText'))

    match intent:
        case 'SelectGroup':
            select_group(message)
        case 'CheckSchedule':
            check_schedule(message, query_result_dict.get('queryResult').get('parameters'))
        case _:
            hide_keyboard = types.ReplyKeyboardRemove()
            bot.send_message(message.chat.id, query_result_dict.get('queryResult').get('fulfillmentText'), reply_markup=hide_keyboard)


def init():
    global items, unidecode_teachers
    background_thread = Thread(target=background_tasks)
    background_thread.start()
    if os.path.isfile('items.json'):
        items = json.load(open('items.json'))
    fill_items_dict()
    unidecode_teachers = [unidecode(t.lower()) for t in items.get('teachers').values()]


# # Run the bot
init()
bot.polling(non_stop=True)





# while True:
#     # Example usage
#     search_string = input("Enter a search string: ")
#     teachers = items.get('teachers').values()
#     match = match_teacher(search_string)
#
#     if match is None:
#         print("No match found.")
#     elif match in teachers:
#         print(f"Exact match found: {match}")
#     else:
#         print(f"Fuzzy match found: {match}")
#         for m in match:
#             print(find_teacher_key(m))
