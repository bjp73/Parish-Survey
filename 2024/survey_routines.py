
#set exception
class UserException(Exception):
    pass    

class EntryException(Exception):
    pass    


def check_data(data, upper_val:6, lower_val:0, allow_multi:False, allow_text:False, text_no:0):

#return list everytime there's "allow multi"
   
    '''    
    if isinstance(data, float): #if float convert to string
        if data%1 > 0:
            raise EntryException(f"Bad data entry: {data}")
        else:
            data = f'{int(data)}'
    
    if isinstance(data, int):
        data = f'{data}'
    '''
    
    if data.isnumeric():
        if int(data) > upper_val or int(data) < lower_val:
            raise EntryException()
        else: 
            return [int(data)]

    #join text that has commas and remove leading number form text if it matches the text_no value
    text = ''
    output = list()
    bits = data.split(',') #split by comma
    if len(bits) > 1:
    
        bits.reverse()
        found_num = False
        for s in bits:
            if s.isnumeric():
                found_num = True
                output.insert(0,s)
            else:
                if found_num:
                    raise UserException()  #should not find non-numeric value after number
                else:
                    if len(text) > 0:
                        text = s + "," + text
                    else:
                        text = s   
    else:  #if only one item in list
        text = bits[0]
        
    #now remove number form start of text if it matches text no 
    if len(text) > 0:
        #check if there's a number at the start and remove items
        ts = text.split(" ")
        if ts[0].isnumeric():
            if int(ts[0]) == text_no:
                text = text[len(ts[0])+1:]
        output.append(text)

    #now process bits to clean
    bits = output
    if len(bits) > 1:   
        if not(allow_multi):
            if bits[0].isnumeric() or not(allow_text):
                raise UserException()
            else: 
                return [data]
        else:
            return_list = list()
            for b, bit in enumerate(bits):
                if bit.isnumeric():
                    if int(bit) > upper_val or int(bit) < lower_val:
                        raise EntryException()
                    elif int(bit) in return_list:  #check for duplicate
                        raise EntryException()
                    else:      
                        return_list.append(int(bit))
                else:
                    if allow_text:
                        return_list.append(text_no)
                        s = ','
                        return_list.append(s.join(bits[b:]))
                    else:
                        raise EntryException()
            return return_list
            
    else:
        if allow_text:
            return [text_no, bits[0]]
        else:    
            raise EntryException()
            
 
   
